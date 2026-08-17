function cleanProjectPath(projectPath) {
  const path = (projectPath || '').replace(/^\/+/, '').replace(/\.git$/, '')
  return path ? `${path}.git` : ''
}

export function parseGitRemote(remote) {
  const s = (remote || '').trim()
  if (!s) return { protocol: 'ssh', user: 'git', path: '' }
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) {
    try {
      const u = new URL(s)
      const username = decodeURIComponent(u.username || '')
      const password = decodeURIComponent(u.password || '')
      return {
        protocol: u.protocol.replace(/:$/, '').toLowerCase(),
        user: username,
        password,
        path: `${u.pathname.replace(/^\/+/, '')}${u.search || ''}`,
      }
    } catch {
      return { protocol: 'ssh', user: 'git', path: '' }
    }
  }
  const scp = s.match(/^(?:(.+?)@)?([^:/]+):(.+)$/)
  if (scp) return { protocol: 'ssh', user: scp[1] || 'git', path: scp[3] || '' }
  return { protocol: 'ssh', user: 'git', path: '' }
}

export function buildGitRemoteWithHostPort(remote, projectPath, host, port) {
  const parsed = parseGitRemote(remote)
  const path = parsed.path || cleanProjectPath(projectPath)
  if (!path) return remote
  const cleanPath = path.endsWith('.git') || path.includes('?') ? path : `${path}.git`
  const protocol = parsed.protocol || 'ssh'
  const user = parsed.user || (protocol === 'ssh' ? 'git' : '')
  const password = parsed.password || ''
  const auth = user
    ? `${encodeURIComponent(user)}${password ? `:${encodeURIComponent(password)}` : ''}@`
    : ''
  return `${protocol}://${auth}${host}:${port}/${cleanPath}`
}

export function buildGitRemoteWithOriginVar(remote, projectPath, originVar = '{{ssh_origin}}') {
  const parsed = parseGitRemote(remote)
  const path = parsed.path || cleanProjectPath(projectPath)
  if (!path) return remote
  const cleanPath = path.endsWith('.git') || path.includes('?') ? path : `${path}.git`
  return `${originVar.replace(/\/+$/, '')}/${cleanPath.replace(/^\/+/, '')}`
}

export function normalizeGitRemoteVarName(name) {
  return String(name || '')
    .trim()
    .replace(/^\{\{\s*/, '')
    .replace(/\s*\}\}$/, '')
    .replace(/^\$\{\s*/, '')
    .replace(/\s*\}$/, '')
}

export function formatGitRemoteVar(name) {
  const clean = normalizeGitRemoteVarName(name) || 'ssh_origin'
  return `{{${clean}}}`
}

export function gitRemoteVariableOptions(presets = [], global = {}) {
  const list = Array.isArray(presets) ? presets : []
  const options = list
    .map((preset) => {
      const variable = normalizeGitRemoteVarName(preset.variable) || 'ssh_origin'
      const origin = (preset.origin || '').trim().replace(/\/+$/, '')
      if (!variable || !origin) return null
      return {
        label: preset.name || formatGitRemoteVar(variable),
        value: formatGitRemoteVar(variable),
        variable: formatGitRemoteVar(variable),
        preview: origin,
      }
    })
    .filter(Boolean)
  if (options.length) return options
  const sshIp = global.ssh_ip || ''
  const sshPort = global.ssh_port || ''
  const origin = (global.ssh_origin || (sshIp && sshPort ? `ssh://git@${sshIp}:${sshPort}` : '')).replace(/\/+$/, '')
  return [{ label: '默认', value: '{{ssh_origin}}', variable: '{{ssh_origin}}', preview: origin }]
}
