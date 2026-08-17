import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useProjectsStore } from './projects'

const COLLAPSE_KEY = 'execCollapsed'

function commitCountSignature(project) {
  return [
    project.local_dir || '',
    project.source_branch || '',
    (project.target_branches || []).join(','),
  ].join('|')
}

export const useMergeStore = defineStore('merge', {
  state: () => ({
    busy: false,
    logs: [], // [{ id, text, cls }]
    lastLogId: 0,
    collapsed: false,
    timer: null,
    commandLogTimer: null,
    commandStreaming: false,
    commandSessionDepth: 0,
    undo: null, // { has_undo, merged_at, items } 最近一次合并的撤回快照
    commitCounts: {}, // projectId -> { loading, total, targets, error }
  }),

  actions: {
    resetLogs() {
      this.logs = []
      this.lastLogId = 0
    },

    async clearLog() {
      this.resetLogs()
      try {
        await api.clear()
      } catch (e) {
        ElMessage.error('清空日志失败：' + e.message)
      }
    },

    appendLogs(entries) {
      entries.forEach(([id, text]) => {
        let cls = 'info'
        if (text.includes('[ERROR]')) cls = 'error'
        else if (text.includes('[WARNING]')) cls = 'warn'
        this.logs.push({ id, text, cls })
      })
    },

    async fetchCommandLogs() {
      const lr = await api.logs(this.lastLogId)
      if (lr.logs && lr.logs.length) {
        this.appendLogs(lr.logs)
        this.lastLogId = lr.since || this.lastLogId
      }
    },

    async startCommandLogSession({ clear = false, reveal = true } = {}) {
      this.commandSessionDepth += 1
      if (this.commandSessionDepth > 1) return
      if (reveal) this.collapsed = false
      this.commandStreaming = true
      clearInterval(this.commandLogTimer)
      if (clear) {
        try {
          await api.clear()
        } catch {
          /* ignore */
        }
        this.resetLogs()
      } else {
        try {
          const r = await api.logs(0)
          this.lastLogId = r.since || this.lastLogId
        } catch {
          /* ignore */
        }
      }
      this.commandLogTimer = setInterval(() => {
        this.fetchCommandLogs().catch((e) => console.error('命令日志轮询失败', e))
      }, 300)
    },

    async stopCommandLogSession() {
      this.commandSessionDepth = Math.max(0, this.commandSessionDepth - 1)
      if (this.commandSessionDepth > 0) return
      clearInterval(this.commandLogTimer)
      this.commandLogTimer = null
      try {
        await this.fetchCommandLogs()
      } catch {
        /* ignore */
      }
      this.commandStreaming = false
    },

    async runWithCommandLog(action, options = {}) {
      await this.startCommandLogSession(options)
      try {
        return await action()
      } finally {
        await this.stopCommandLogSession()
      }
    },

    async runMerge() {
      if (this.busy) return
      const projectsStore = useProjectsStore()
      const checking = projectsStore.checkedProjects.some((p) => this.commitCounts[p.id]?.loading)
      if (checking) {
        ElMessage.warning('正在检测待合并 commit 数量，请稍后再开始合并')
        return
      }
      const configured = projectsStore.checkedProjects.filter((p) =>
        p.ssh_host && p.source_branch && p.target_branches && p.target_branches.length
      )
      const unchecked = configured.find((p) => {
        const stat = this.commitCounts[p.id]
        return !stat || stat.loading || stat.error
      })
      if (unchecked) {
        ElMessage.warning(`工程「${unchecked.name || unchecked.ssh_host}」的 commit 数量尚未检测成功`)
        return
      }
      const selected = configured
        .map((p) => {
          const stat = this.commitCounts[p.id]
          const targets = (p.target_branches || []).filter((t) => (stat.targets[t] || 0) > 0)
          return { project: p, targets }
        })
        .filter((x) => x.targets.length)
      if (!selected.length) {
        ElMessage.error('没有可执行的工程：已勾选工程均无合并内容或未勾选工程')
        return
      }
      for (let i = 0; i < selected.length; i++) {
        const s = selected[i].project
        if (!s.ssh_host || !s.source_branch || !s.target_branches.length) {
          ElMessage.error(`第 ${i + 1} 个工程配置不完整（需要 SSH 地址、源分支、目标分支）`)
          return
        }
      }
      this.collapsed = false
      try {
        await api.clear()
      } catch (e) {
        /* 忽略清空失败 */
      }
      this.resetLogs()
      // 新合并开始，旧撤回快照作废
      this.undo = null
      const payload = selected.map(({ project, targets }) => {
        const { id, checked, branches, ...rest } = project
        return { ...rest, target_branches: targets }
      })
      try {
        const r = await api.merge(payload, { ...projectsStore.global })
        if (r && r.status === 'started') this.startPolling()
      } catch (e) {
        ElMessage.error('启动合并失败：' + e.message)
      }
    },

    async refreshCommitCount(project) {
      if (!project || !project.id) return
      const signature = commitCountSignature(project)
      const current = this.commitCounts[project.id]
      if (current && current.signature === signature && (current.loading || !current.error)) return
      if (!project.local_dir || !project.source_branch || !project.target_branches || !project.target_branches.length) {
        this.commitCounts = {
          ...this.commitCounts,
          [project.id]: { loading: false, total: null, targets: {}, error: '配置不完整', signature },
        }
        return
      }
      this.commitCounts = {
        ...this.commitCounts,
        [project.id]: { loading: true, total: null, targets: {}, error: '', signature },
      }
      try {
        await this.startCommandLogSession({ reveal: false })
        const results = await Promise.all(project.target_branches.map(async (target) => {
          const r = await api.mergeRange({
            local_dir: project.local_dir,
            source_branch: project.source_branch,
            target_branch: target,
            limit: 1,
          })
          return [target, r.total || 0]
        }))
        const latest = this.commitCounts[project.id]
        if (!latest || latest.signature !== signature) return
        const targets = Object.fromEntries(results)
        const total = results.reduce((sum, [, n]) => sum + n, 0)
        this.commitCounts = {
          ...this.commitCounts,
          [project.id]: { loading: false, total, targets, error: '', signature },
        }
      } catch (e) {
        const latest = this.commitCounts[project.id]
        if (!latest || latest.signature !== signature) return
        this.commitCounts = {
          ...this.commitCounts,
          [project.id]: { loading: false, total: null, targets: {}, error: e.message, signature },
        }
      } finally {
        await this.stopCommandLogSession()
      }
    },

    // 查询最近一次合并的可撤回状态（合并完成后 / 页面加载时调用）
    async fetchUndo() {
      try {
        this.undo = await api.mergeUndo()
      } catch (e) {
        /* 静默：无撤回记录属于正常情况 */
        this.undo = { has_undo: false }
      }
    },

    // 撤回最近一次合并
    async undoMerge() {
      if (this.busy) return
      try {
        const r = await api.mergeUndoRun()
        if (r && r.status === 'started') {
          ElMessage.info('开始撤回合并，日志将实时显示进度')
          this.startPolling()
        }
      } catch (e) {
        ElMessage.error('启动撤回失败：' + e.message)
      }
    },

    startPolling() {
      this.busy = true
      this.commandStreaming = false
      this.commandSessionDepth = 0
      clearInterval(this.commandLogTimer)
      this.commandLogTimer = null
      clearInterval(this.timer)
      this.timer = setInterval(async () => {
        try {
          const [lr, st] = await Promise.all([
            api.logs(this.lastLogId),
            api.state(),
          ])
          if (lr.logs && lr.logs.length) {
            this.appendLogs(lr.logs)
            this.lastLogId = lr.since || this.lastLogId
          }
          const wasBusy = this.busy
          this.busy = !!st.busy
          if (!this.busy && wasBusy) {
            clearInterval(this.timer)
            this.timer = null
            ElMessage.success('任务执行完成')
            // 合并/撤回结束后刷新「撤回合并」可用状态
            this.fetchUndo()
          }
        } catch (e) {
          console.error('日志轮询失败', e)
        }
      }, 800)
    },

    stopPolling() {
      clearInterval(this.timer)
      this.timer = null
    },

    toggleCollapsed() {
      this.collapsed = !this.collapsed
      try {
        localStorage.setItem(COLLAPSE_KEY, this.collapsed ? '1' : '0')
      } catch (e) {
        /* ignore */
      }
    },

    restoreCollapsed() {
      try {
        const v = localStorage.getItem(COLLAPSE_KEY)
        this.collapsed = v === null ? false : v === '1'
      } catch (e) {
        this.collapsed = false
      }
    },
  },
})
