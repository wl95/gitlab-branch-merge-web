import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { api } from '../api'

let uid = 1

function blankProject() {
  return {
    id: uid++,
    name: '',
    ssh_host: '',
    project_path: '',
    source_branch: '',
    target_branches: [],
    local_dir: '',
    checked: false,
    branches: [], // 该工程已加载的分支列表缓存
    branchesLoading: false, // 该工程是否正在加载分支
  }
}

export const useProjectsStore = defineStore('projects', {
  state: () => ({
    projects: [],
    global: { ssh_host: '', source_branch: '', target_branches: [] },
    globalBranches: [],
    globalBranchesLoading: false, // 全局分支是否正在加载
    // ⚠ 必须与 actions.scanFolder 区分开（Pinia actions 会覆盖同名 state），
    // 所以这里用 scanFolderPath 存储用户输入的目录路径。
    // 持久化到 localStorage：刷新页面自动恢复上次的目录，避免重复复制
    scanFolderPath: localStorage.getItem('gm_scan_folder') || '',
    // 扫描过的目录历史（多目录记录，点击即可切换，避免每次复制粘贴）
    scanHistory: (() => {
      try {
        const h = JSON.parse(localStorage.getItem('gm_scan_history') || '[]')
        return Array.isArray(h) ? h : []
      } catch {
        return []
      }
    })(),
    scanResult: null, // { repos: [{host, name, project_path, path}], warnings: [...] }
    scanLoading: false,
    scanShow: false,
    lastAddedId: null, // 最近新增工程 id，用于自动聚焦
    profiles: [], // 已保存的配置方案摘要列表 [{name, updated, project_count, target_branches}]
    profilesLoading: false,
  }),

  getters: {
    count: (s) => s.projects.length,
    checkedProjects: (s) => s.projects.filter((p) => p.checked),
  },

  actions: {
    // ---------- 公共：工程唯一键 & 去重 ----------

    // 工程唯一键：ssh_host 优先，回退到 name+local_dir
    // （同名未填 ssh_host 的工程视为重复，避免连续点「＋ 添加」产生多个空卡片）
    _projectKey(p) {
      const ssh = (p.ssh_host || '').trim()
      if (ssh) return `ssh:${ssh}`
      const local = (p.local_dir || '').trim()
      if (local) return `local:${local}|${(p.name || '').trim()}`
      return `blank:${(p.name || '').trim()}:${uid}`
    },

    // 对传入的工程列表按唯一键去重（保留首次出现）
    _dedupeProjects(list) {
      const seen = new Set()
      const out = []
      for (const p of list) {
        const k = this._projectKey(p)
        if (seen.has(k)) continue
        seen.add(k)
        out.push(p)
      }
      return out
    },

    addProject(data = {}) {
      // 已存在同 ssh_host+project_path 的工程：返回已存在项，自动聚焦，不重复添加
      if (data.ssh_host || data.local_dir) {
        const existed = this.projects.find((p) =>
          (data.ssh_host && p.ssh_host === data.ssh_host) ||
          (data.local_dir && p.local_dir === data.local_dir && !(data.ssh_host || p.ssh_host))
        )
        if (existed) {
          this.lastAddedId = existed.id
          return existed
        }
      }
      const p = blankProject()
      if (data.name) p.name = data.name
      if (data.ssh_host) p.ssh_host = data.ssh_host
      if (data.project_path) p.project_path = data.project_path
      if (data.local_dir) p.local_dir = data.local_dir
      this.projects.push(p)
      this.lastAddedId = p.id
      return p
    },

    removeProject(id) {
      const i = this.projects.findIndex((p) => p.id === id)
      if (i < 0) return null
      const [removed] = this.projects.splice(i, 1)
      return removed
    },

    setAllChecked(checked) {
      this.projects.forEach((p) => {
        p.checked = checked
      })
    },

    removeCheckedProjects() {
      const removed = this.projects.filter((p) => p.checked)
      if (!removed.length) return []
      this.projects = this.projects.filter((p) => !p.checked)
      return removed
    },

    restoreProjects(list) {
      const restored = []
      ;(list || []).forEach((data) => {
        const p = this.addProject({
          name: data.name || '',
          ssh_host: data.ssh_host || '',
          project_path: data.project_path || '',
          local_dir: data.local_dir || '',
        })
        p.source_branch = data.source_branch || ''
        p.target_branches = Array.isArray(data.target_branches) ? [...data.target_branches] : []
        p.checked = false
        restored.push(p)
      })
      return restored
    },

    setBranches(id, branches) {
      const p = this.projects.find((x) => x.id === id)
      if (p) p.branches = Array.isArray(branches) ? branches : []
    },

    // 加载单个工程的分支（用于加入/修改 ssh_host 后自动触发）。
    // 静默调用：失败不弹错（避免用户输入过程中频繁弹错误），由卡片显示加载态。
    async loadBranchesFor(id) {
      const p = this.projects.find((x) => x.id === id)
      if (!p) return
      if (!p.ssh_host || !p.ssh_host.trim()) return
      if (p.branchesLoading) return // 已在加载中，跳过避免重复请求
      p.branchesLoading = true
      try {
        const branches = await this.loadBranches({
          ssh_host: p.ssh_host,
          project_path: p.project_path,
        })
        this.setBranches(id, branches)
      } catch (e) {
        console.error(`自动加载分支失败（${p.ssh_host}）：`, e)
      } finally {
        p.branchesLoading = false
      }
    },

    async loadState() {
      const st = await api.state()
      const mapped = (st.projects || []).map((p) => ({
        id: uid++,
        ...p,
        checked: false,
        branches: [],
        branchesLoading: false,
      }))
      this.projects = this._dedupeProjects(mapped)
      this.global = st.global || {
        ssh_host: '',
        source_branch: '',
        target_branches: [],
      }
      return st
    },

    // 进入页面时自动加载全部分支（全局 + 各工程），失败静默降级
    async autoLoadBranches() {
      const globalTask = (async () => {
        if (!this.global.ssh_host.trim()) return
        this.globalBranchesLoading = true
        try {
          this.globalBranches = await this.loadBranches({
            ssh_host: this.global.ssh_host,
          })
        } catch (e) {
          console.error('自动加载全局分支失败：', e)
        } finally {
          this.globalBranchesLoading = false
        }
      })()

      const projectTasks = this.projects
        .filter((p) => p.ssh_host.trim())
        .map(async (p) => {
          p.branchesLoading = true
          try {
            const branches = await this.loadBranches({
              ssh_host: p.ssh_host,
              project_path: p.project_path,
            })
            this.setBranches(p.id, branches)
          } catch (e) {
            console.error(`自动加载分支失败（${p.ssh_host}）：`, e)
          } finally {
            p.branchesLoading = false
          }
        })

      await Promise.all([globalTask, ...projectTasks])
    },

    async save() {
      const projects = this._serializableProjects()
      const r = await api.save(projects, { ...this.global })
      // 用服务端规范化后的数据回填，保留本地 id / 勾选 / 分支缓存
      const server = r.projects || []
      const norm = new Map(server.map((p) => [p.ssh_host + '|' + p.project_path, p]))
      this.projects.forEach((p) => {
        const key = p.ssh_host + '|' + p.project_path
        const n = norm.get(key)
        if (n) {
          p.name = n.name
          p.source_branch = n.source_branch
          p.target_branches = n.target_branches || []
        }
      })
      if (r.global) this.global = r.global
      return r
    },

    async loadBranches(payload) {
      const r = await api.branches(payload)
      return r.branches || []
    },

    async loadGlobalBranches() {
      if (!this.global.ssh_host.trim()) {
        ElMessage.error('请先填写全局 SSH 地址')
        return []
      }
      const branches = await this.loadBranches({
        ssh_host: this.global.ssh_host,
      })
      this.globalBranches = branches
      if (!branches.length) ElMessage.warning('未发现可用的分支')
      return branches
    },

    // 记录扫描过的目录到历史（去重置顶，最多保留 15 条）
    rememberScanFolder(folder) {
      if (!folder) return
      this.scanHistory = [
        folder,
        ...this.scanHistory.filter((f) => f !== folder),
      ].slice(0, 15)
      localStorage.setItem('gm_scan_history', JSON.stringify(this.scanHistory))
    },

    clearScanHistory() {
      this.scanHistory = []
      localStorage.removeItem('gm_scan_history')
    },

    async scanFolder() {
      if (!this.scanFolderPath || !this.scanFolderPath.trim()) {
        ElMessage.error('请先输入要读取的文件夹路径')
        return
      }
      this.scanLoading = true
      this.scanShow = true
      this.scanResult = null
      const folder = this.scanFolderPath.trim()
      // 记录目录：上次使用 + 历史列表，下次打开页面自动填充 / 一键切换
      localStorage.setItem('gm_scan_folder', folder)
      this.rememberScanFolder(folder)
      try {
        const r = await api.scan(folder)
        this.scanResult = r
      } catch (e) {
        this.scanResult = { repos: [], warnings: ['读取失败：' + e.message] }
      } finally {
        this.scanLoading = false
      }
    },

    addScanned(repo) {
      // 已存在则跳过（按 ssh_host 或本地路径匹配）
      if (this.projects.some((p) =>
        (repo.ssh_host && p.ssh_host === repo.ssh_host) ||
        (!repo.ssh_host && repo.path && p.local_dir === repo.path)
      )) {
        ElMessage.warning(`工程「${repo.name || repo.ssh_host || repo.path}」已存在，跳过`)
        return
      }
      const p = this.addProject({
        name: repo.name || '',
        ssh_host: repo.ssh_host || '',
        project_path: repo.project_path || '',
        local_dir: repo.path || '',
      })
      ElMessage.success(`已加入工程「${repo.name || repo.ssh_host || repo.path}」`)
      // 扫描加入的仓库自带 ssh_host，立即自动加载分支
      if (p && p.ssh_host) this.loadBranchesFor(p.id)
    },

    removeScanned(repo) {
      const p = this.projects.find((x) =>
        (repo.ssh_host && x.ssh_host === repo.ssh_host) ||
        (!repo.ssh_host && repo.path && x.local_dir === repo.path)
      )
      if (!p) return
      if (p.source_branch || p.target_branches.length) {
        ElMessage.warning('该工程已配置分支，请在卡片中手动删除')
        return
      }
      this.removeProject(p.id)
      ElMessage.success('已移除该工程')
    },

    applyGlobalSource() {
      if (!this.global.source_branch.trim()) {
        ElMessage.warning('请先填写全局源分支')
        return
      }
      this.projects.forEach((p) => {
        p.source_branch = this.global.source_branch
      })
      ElMessage.success('已为全部工程应用全局源分支')
    },

    applyGlobalTargets() {
      if (!this.global.target_branches.length) {
        ElMessage.warning('请先添加全局目标分支')
        return
      }
      this.projects.forEach((p) => {
        p.target_branches = [...this.global.target_branches]
      })
      ElMessage.success('已为全部工程应用全局目标分支')
    },

    applyGlobalAll() {
      this.applyGlobalSource()
      this.applyGlobalTargets()
    },

    // ---------- 配置方案（profiles） ----------

    // 将 store 内的工程数据转换为服务端格式（去除前端临时字段）
    _serializableProjects() {
      return this.projects.map(({ id, checked, branches, branchesLoading, ...rest }) => rest)
    },

    async loadProfiles() {
      this.profilesLoading = true
      try {
        const r = await api.profiles()
        this.profiles = r.profiles || []
        return this.profiles
      } catch (e) {
        ElMessage.error('加载配置方案失败：' + e.message)
        return []
      } finally {
        this.profilesLoading = false
      }
    },

    // 保存当前配置为新方案；name 为空时后端按全局目标分支自动命名
    async saveProfile(name) {
      const r = await api.profileSave(name, this._serializableProjects(), { ...this.global })
      const g = this.global || {}
      const src = (g.source_branch || '').trim()
      const tgt = (g.target_branches || []).join(',')
      ElMessage.success(
        `方案「${r.name}」已保存` +
        (src || tgt ? `（源分支: ${src || '-'} → 目标分支: ${tgt || '-'}）` : '')
      )
      await this.loadProfiles()
      return r
    },

    // 加载指定方案：替换当前工程列表与全局配置，并重新拉取分支
    async loadProfile(name) {
      const r = await api.profileLoad(name)
      const mapped = (r.projects || []).map((p) => ({
        id: uid++,
        ...p,
        checked: false,
        branches: [],
        branchesLoading: false,
      }))
      this.projects = this._dedupeProjects(mapped)
      this.global = r.global || {
        ssh_host: '',
        source_branch: '',
        target_branches: [],
      }
      ElMessage.success(`已切换到方案「${name}」`)
      // 切换后并发触发每个工程的分支加载，UI 立即可见
      this.projects
        .filter((p) => p.ssh_host && p.ssh_host.trim())
        .forEach((p) => this.loadBranchesFor(p.id))
      return r
    },

    async deleteProfile(name) {
      await api.profileDelete(name)
      this.profiles = this.profiles.filter((p) => p.name !== name)
      ElMessage.success(`方案「${name}」已删除`)
    },
  },
})
