import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useProjectsStore } from './projects'

const PAGE_SIZE = 50

export const usePickStore = defineStore('pick', {
  state: () => ({
    visible: false,
    ctx: null, // 工程快照 { id, name, ssh_host, project_path, local_dir, source_branch, target_branches }
    sourceBranch: '',
    commits: [], // 源分支已加载的 commit（分页累计）
    loading: false,
    loadingMore: false,
    page: 1,
    total: 0,
    hasMore: false,
    searchKw: '',
    selected: [], // 已勾选的 sha 列表
    pickTarget: '',
    viewTargetBranch: '',
    targetCommits: [],
    targetLoading: false,
    picking: false,
  }),

  getters: {
    targets: (s) => (s.ctx && s.ctx.target_branches ? s.ctx.target_branches : []),
    selectedCount: (s) => s.selected.length,
    filteredCommits: (s) => {
      const kw = s.searchKw.trim().toLowerCase()
      if (!kw) return s.commits
      return s.commits.filter((c) =>
        (c.subject + ' ' + c.sha + ' ' + c.short + ' ' + c.author).toLowerCase().includes(kw)
      )
    },
    isSelected: (s) => (sha) => s.selected.includes(sha),
  },

  actions: {
    _ctxPayload() {
      const c = this.ctx
      return {
        ssh_host: c.ssh_host,
        project_path: c.project_path,
        local_dir: c.local_dir,
        source_branch: c.source_branch,
        target_branches: c.target_branches,
      }
    },

    open(projectId) {
      const projectsStore = useProjectsStore()
      const p = projectsStore.projects.find((x) => x.id === projectId)
      if (!p) return
      this.ctx = {
        id: p.id,
        name: p.name,
        ssh_host: p.ssh_host,
        project_path: p.project_path,
        local_dir: p.local_dir,
        source_branch: p.source_branch,
        target_branches: [...p.target_branches],
      }
      this.sourceBranch = p.source_branch || ''
      this.commits = []
      this.page = 1
      this.total = 0
      this.hasMore = false
      this.searchKw = ''
      this.selected = []
      this.pickTarget = ''
      this.viewTargetBranch = (p.target_branches && p.target_branches[0]) || ''
      this.targetCommits = []
      this.visible = true
      if (this.sourceBranch) this.loadCommits(true)
      if (this.viewTargetBranch) this.loadTargetCommits(this.viewTargetBranch)
    },

    close() {
      this.visible = false
      this.ctx = null
    },

    toggle(sha) {
      const i = this.selected.indexOf(sha)
      if (i >= 0) this.selected.splice(i, 1)
      else this.selected.push(sha)
    },

    async loadCommits(reset = true) {
      const c = this.ctx
      if (!c) return
      if (!c.ssh_host) {
        ElMessage.error('请先填写 SSH 地址')
        return
      }
      if (!this.sourceBranch) return
      if (reset) {
        this.loading = true
        this.page = 1
      } else {
        this.loadingMore = true
      }
      try {
        const r = await api.commits({
          ...this._ctxPayload(),
          branch: this.sourceBranch,
          page: this.page,
          page_size: PAGE_SIZE,
        })
        this.commits = reset ? r.commits || [] : this.commits.concat(r.commits || [])
        this.total = r.total || 0
        this.hasMore = !!r.has_more
      } catch (e) {
        if (reset) this.commits = []
        ElMessage.error((reset ? '获取 commit 失败：' : '加载更多失败：') + e.message)
      } finally {
        this.loading = false
        this.loadingMore = false
      }
    },

    loadMore() {
      if (!this.hasMore || this.loading || this.loadingMore) return
      this.page += 1
      this.loadCommits(false)
    },

    async loadTargetCommits(branch) {
      const c = this.ctx
      this.viewTargetBranch = branch
      if (!branch) {
        this.targetCommits = []
        return
      }
      if (!c || !c.ssh_host) {
        ElMessage.error('请先填写 SSH 地址')
        return
      }
      this.targetLoading = true
      this.targetCommits = []
      try {
        const r = await api.commits({
          ...this._ctxPayload(),
          branch,
          page: 1,
          page_size: PAGE_SIZE,
        })
        this.targetCommits = r.commits || []
      } catch (e) {
        this.targetCommits = []
        ElMessage.error('获取目标分支 commit 失败：' + e.message)
      } finally {
        this.targetLoading = false
      }
    },

    async doPick() {
      const c = this.ctx
      if (!c) return
      if (!c.ssh_host) {
        ElMessage.error('请先填写 SSH 地址')
        return
      }
      if (!this.selected.length) {
        ElMessage.error('请至少勾选一个 commit')
        return
      }
      if (!this.pickTarget) {
        ElMessage.error('请选择要 Pick 的目标分支')
        return
      }
      this.picking = true
      try {
        const r = await api.cherryPick({
          ...this._ctxPayload(),
          target_branch: this.pickTarget,
          commits: this.selected,
        })
        ElMessage.success('✔ ' + (r.message || 'Pick 成功'))
        this.close()
      } catch (e) {
        ElMessage.error('Pick 失败：' + e.message)
      } finally {
        this.picking = false
      }
    },
  },
})
