import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { api } from '../api'

// 待合并 commit 视图全局状态：
//  - visible：弹窗是否显示
//  - ctx：打开时的工程上下文 {id,name,ssh_host,project_path,local_dir,source_branch,target_branches}
//  - currentTarget：当前选的目标分支（多个目标时切换）
//  - items：当前 target 下 source..target 之间的 commits（按时间倒序）
//  - loading：拉取中
//  - openDiff：当前展开查看 diff 的 sha 集合
//  - diffCache：sha -> {state:'loading'|'ok'|'error', data?}
export const useCommitsViewStore = defineStore('commitsView', {
  state: () => ({
    visible: false,
    ctx: null,
    currentTarget: '',
    items: [],
    loading: false,
    openDiff: {},
    diffCache: {},
  }),

  getters: {
    targets: (s) => (s.ctx && s.ctx.target_branches ? s.ctx.target_branches : []),
  },

  actions: {
    async open(p) {
      this.ctx = {
        id: p.id,
        name: p.name,
        ssh_host: p.ssh_host,
        project_path: p.project_path,
        local_dir: p.local_dir,
        source_branch: p.source_branch,
        target_branches: [...(p.target_branches || [])],
      }
      this.openDiff = {}
      this.diffCache = {}
      this.items = []
      this.currentTarget = (p.target_branches && p.target_branches[0]) || ''
      this.visible = true
      if (this.currentTarget) {
        await this._loadRange()
      }
    },

    close() {
      this.visible = false
      this.ctx = null
      this.items = []
      this.currentTarget = ''
      this.openDiff = {}
      this.diffCache = {}
    },

    async selectTarget(t) {
      this.currentTarget = t || ''
      this.items = []
      this.openDiff = {}
      this.diffCache = {}
      if (this.currentTarget) await this._loadRange()
    },

    async _loadRange() {
      const c = this.ctx
      if (!c || !c.local_dir) {
        ElMessage.error('请先填写工程配置后再查看')
        return
      }
      if (!c.source_branch) {
        ElMessage.warning('请先选择源分支')
        return
      }
      if (!this.currentTarget) {
        ElMessage.warning('请先选择目标分支')
        return
      }
      this.loading = true
      try {
        const r = await api.mergeRange({
          local_dir: c.local_dir,
          source_branch: c.source_branch,
          target_branch: this.currentTarget,
        })
        this.items = r.items || []
        if (!this.items.length) {
          ElMessage.info('该目标分支暂无即将合并的新 commit')
        }
      } catch (e) {
        this.items = []
        ElMessage.error('获取 commit 列表失败：' + e.message)
      } finally {
        this.loading = false
      }
    },

    async toggleDiff(sha) {
      if (this.openDiff[sha]) {
        delete this.openDiff[sha]
        return
      }
      this.openDiff = { ...this.openDiff, [sha]: true }
      if (this.diffCache[sha]) return
      this.diffCache = { ...this.diffCache, [sha]: { state: 'loading' } }
      try {
        const r = await api.commitDiff({
          local_dir: this.ctx.local_dir,
          sha,
        })
        this.diffCache = { ...this.diffCache, [sha]: { state: 'ok', data: r } }
      } catch (e) {
        this.diffCache = {
          ...this.diffCache,
          [sha]: { state: 'error', error: e.message },
        }
      }
    },
  },
})
