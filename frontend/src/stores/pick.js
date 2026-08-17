import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useProjectsStore } from './projects'
import { useMergeStore } from './merge'

const PAGE_SIZE = 50

export const usePickStore = defineStore('pick', {
  state: () => ({
    visible: false,
    ctx: null, // 工程快照 { id, name, ssh_host, project_path, local_dir, source_branch, target_branches, branches }
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
    pickTargets: (s) => {
      const branches = s.ctx && s.ctx.branches ? s.ctx.branches : []
      const mergeTargets = new Set(s.ctx && s.ctx.target_branches ? s.ctx.target_branches : [])
      return branches.filter((b) => b && b !== s.sourceBranch && !mergeTargets.has(b))
    },
    pickCascade: (s) => {
      const targets = s.ctx && s.ctx.target_branches ? s.ctx.target_branches : []
      if (!s.pickTarget) return []
      const index = targets.indexOf(s.pickTarget)
      if (index < 0) return targets
      return targets.slice(index + 1)
    },
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
      const projectsStore = useProjectsStore()
      return {
        ssh_host: c.ssh_host,
        project_path: c.project_path,
        local_dir: c.local_dir,
        source_branch: c.source_branch,
        target_branches: c.target_branches,
        gitlab_url: c.gitlab_url,
        gitlab_project_id: c.gitlab_project_id,
        gitlab_token: c.gitlab_token,
        gitlab_api_version: c.gitlab_api_version,
        gitlab_token_in_query: c.gitlab_token_in_query,
        global: { ...projectsStore.global },
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
        branches: [...(p.branches || [])],
        gitlab_url: p.gitlab_url,
        gitlab_project_id: p.gitlab_project_id,
        gitlab_token: p.gitlab_token,
        gitlab_api_version: p.gitlab_api_version,
        gitlab_token_in_query: p.gitlab_token_in_query,
      }
      this.sourceBranch = p.source_branch || ''
      this.commits = []
      this.page = 1
      this.total = 0
      this.hasMore = false
      this.searchKw = ''
      this.selected = []
      this.pickTarget = this.pickTargets[0] || ''
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

    refreshPickTarget() {
      if (!this.pickTarget || !this.pickTargets.includes(this.pickTarget)) {
        this.pickTarget = this.pickTargets[0] || ''
      }
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
        const merge = useMergeStore()
        const r = await merge.runWithCommandLog(() => api.commits({
          ...this._ctxPayload(),
          branch: this.sourceBranch,
          page: this.page,
          page_size: PAGE_SIZE,
        }), { reveal: false })
        this.commits = reset ? r.commits || [] : this.commits.concat(r.commits || [])
        this.total = r.total || 0
        this.hasMore = !!r.has_more
        this.refreshPickTarget()
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
        const merge = useMergeStore()
        const r = await merge.runWithCommandLog(() => api.commits({
          ...this._ctxPayload(),
          branch,
          page: 1,
          page_size: PAGE_SIZE,
        }), { reveal: false })
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
        const merge = useMergeStore()
        const r = await merge.runWithCommandLog(() => api.cherryPick({
          ...this._ctxPayload(),
          target_branch: this.pickTarget,
          commits: this.selected,
        }), { reveal: false })
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
