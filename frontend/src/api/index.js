// 后端 API 封装：统一处理 JSON 解析与错误抛出

async function request(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== null) opts.body = JSON.stringify(body)
  const res = await fetch('/api' + path, opts)
  let data = null
  try {
    data = await res.json()
  } catch (e) {
    /* 非 JSON 响应 */
  }
  if (!res.ok) {
    throw new Error((data && data.error) || `请求失败 (${res.status})`)
  }
  if (data && data.ok === false) {
    throw new Error(data.error || '操作失败')
  }
  return data
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
  profileLoad: (name) => request('/profile/load', 'POST', { name }),
  profileDelete: (name) => request('/profile/delete', 'POST', { name }),
  profileRestore: (name, profile) => request('/profile/restore', 'POST', { name, profile }),
}
