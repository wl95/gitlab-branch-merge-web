// 后端 API 封装：统一处理 JSON 解析与错误抛出

function apiCandidates(path) {
  const urls = [`/api${path}`, `http://127.0.0.1:8765/api${path}`]
  if (typeof window !== 'undefined' && window.location.origin) {
    urls.splice(1, 0, `${window.location.origin}/api${path}`)
  }
  return [...new Set(urls)]
}

async function request(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== null) opts.body = JSON.stringify(body)
  let last = null
  const errors = []
  for (const url of apiCandidates(path)) {
    try {
      const res = await fetch(url, opts)
      let data = null
      try {
        data = await res.json()
      } catch (e) {
        /* 非 JSON 响应，通常是前端 dev server 的 404/HTML 回退 */
      }

      if (res.ok && !(data && data.ok === false)) return data

      const message = (data && data.error) || (res.ok ? '操作失败' : `请求失败 (${res.status})`)
      last = { url, status: res.status, data, message }

      // 有 JSON 错误体时说明已经命中后端，直接保留业务错误。
      if (data) break
      errors.push(`${url} ${res.status}`)
    } catch (e) {
      errors.push(`${url} ${e.message || '连接失败'}`)
    }
  }

  if (!last) {
    throw new Error(`无法连接后端服务，已尝试：${errors.join('、')}。请确认 ./start_webapp.sh 正在运行，且浏览器访问 http://127.0.0.1:8765/`)
  }
  throw new Error(last.message)
}

async function diagnoseBackend() {
  const checks = []
  for (const path of ['/state', '/commit/report/ping']) {
    for (const url of apiCandidates(path)) {
      try {
        const res = await fetch(url, { method: 'GET' })
        checks.push({ url, ok: res.ok, status: res.status })
        if (res.ok) break
      } catch (e) {
        checks.push({ url, ok: false, error: e.message || '连接失败' })
      }
    }
  }
  const stateOk = checks.some((x) => x.url.includes('/api/state') && x.ok)
  const reportOk = checks.some((x) => x.url.includes('/api/commit/report/ping') && x.ok)
  if (!stateOk) return `后端未响应。诊断：${checks.map((x) => `${x.url} ${x.status || x.error}`).join('；')}`
  if (!reportOk) return `后端正在运行，但不是最新版本或缺少提交统计接口。请停止旧服务后重新执行 ./start_webapp.sh。诊断：${checks.map((x) => `${x.url} ${x.status || x.error}`).join('；')}`
  return ''
}

export const api = {
  state: () => request('/state'),
  branches: (payload) => request('/branches', 'POST', payload),
  scan: (folder) => request('/scan', 'POST', { folder }),
  gitlabProjects: (payload) => request('/gitlab/projects', 'POST', payload),
  gitlabDiagnose: (payload) => request('/gitlab/diagnose', 'POST', payload),
  projectPull: (payload) => request('/project/pull', 'POST', payload),
  save: (projects, global) => request('/save', 'POST', { projects, global }),
  commits: (payload) => request('/commits', 'POST', payload),
  commitReport: (payload) => request('/commit/report', 'POST', payload),
  diagnoseBackend,
  cherryPick: (payload) => request('/cherry-pick', 'POST', payload),
  mergeRange: (payload) => request('/merge/range', 'POST', payload),
  commitDiff: (payload) => request('/commit/diff', 'POST', payload),
  merge: (projects, global) => request('/merge', 'POST', { projects, global }),
  mergeUndo: () => request('/merge/undo'),
  mergeUndoRun: () => request('/merge/undo', 'POST', {}),
  branchCreate: (payload) => request('/branch/create', 'POST', payload),
  branchUndo: () => request('/branch/undo'),
  branchUndoRun: () => request('/branch/undo', 'POST', {}),
  branchCreateUndo: () => request('/branch/undo'),
  branchCreateUndoRun: () => request('/branch/undo', 'POST', {}),
  branchDelete: (payload) => request('/branch/delete', 'POST', payload),
  branchRename: (payload) => request('/branch/rename', 'POST', payload),
  branchSwitchLocal: (payload) => request('/branch/switch-local', 'POST', payload),
  clear: () => request('/clear', 'POST', {}),
  logs: (since) => request(`/logs?since=${since}`),
  auditLogs: () => request('/audit/logs'),
  auditLog: (payload) => request('/audit/log', 'POST', payload),
  auditDelete: (ids) => request('/audit/log/delete', 'POST', { ids }),
  profiles: () => request('/profiles'),
  profileSave: (name, projects, global) =>
    request('/profile/save', 'POST', { name, projects, global }),
  profileGet: (name) => request(`/profile/get?name=${encodeURIComponent(name)}`),
  profileLoad: (name) => request('/profile/load', 'POST', { name }),
  profileDelete: (name) => request('/profile/delete', 'POST', { name }),
  profileRestore: (name, profile) => request('/profile/restore', 'POST', { name, profile }),
}
