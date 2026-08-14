import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useProjectsStore } from './projects'

const COLLAPSE_KEY = 'execCollapsed'

export const useMergeStore = defineStore('merge', {
  state: () => ({
    busy: false,
    logs: [], // [{ id, text, cls }]
    lastLogId: 0,
    collapsed: false,
    timer: null,
    undo: null, // { has_undo, merged_at, items } 最近一次合并的撤回快照
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

    async runMerge() {
      if (this.busy) return
      const projectsStore = useProjectsStore()
      const selected = projectsStore.checkedProjects
      if (!selected.length) {
        ElMessage.error('请至少勾选一个要执行的工程')
        return
      }
      for (let i = 0; i < selected.length; i++) {
        const s = selected[i]
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
      const payload = selected.map(({ id, checked, branches, ...rest }) => rest)
      try {
        const r = await api.merge(payload)
        if (r && r.status === 'started') this.startPolling()
      } catch (e) {
        ElMessage.error('启动合并失败：' + e.message)
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
