export const DEFAULT_SSH_PRESETS = [
  {
    id: 'default-38',
    name: '默认',
    variable: 'ssh_origin',
    host: '38.76.216.46',
    port: '42221',
    origin: 'ssh://git@38.76.216.46:42221',
  },
]

export function normalizeVarName(name) {
  return String(name || '')
    .trim()
    .replace(/^\{\{\s*/, '')
    .replace(/\s*\}\}$/, '')
    .replace(/^\$\{\s*/, '')
    .replace(/\s*\}$/, '')
}

function suggestVarName(item = {}, index = 0) {
  if (item.variable || item.var_name || item.key) return item.variable || item.var_name || item.key
  if (index === 0) return 'ssh_origin'
  const raw = item.name || item.host || `ssh_origin_${index + 1}`
  const clean = String(raw)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return /^[a-z_]/.test(clean) ? clean : `ssh_${clean || index + 1}`
}

export function normalizeSshPreset(item = {}, index = 0) {
  const host = item.host || ''
  const port = item.port || ''
  const variable = normalizeVarName(suggestVarName(item, index))
  return {
    id: item.id || `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    name: item.name || `${host}:${port}`,
    variable,
    host,
    port,
    origin: item.origin || (host && port ? `ssh://git@${host}:${port}` : ''),
  }
}

export function sshVarsFromPresets(presets = []) {
  return presets.reduce((acc, item) => {
    const variable = normalizeVarName(item.variable)
    const origin = (item.origin || '').trim().replace(/\/+$/, '')
    if (variable && origin) acc[variable] = origin
    return acc
  }, {})
}

export function loadSshPresets() {
  try {
    const list = JSON.parse(localStorage.getItem('gm_ssh_presets') || '[]')
    if (Array.isArray(list) && list.length) return list.map(normalizeSshPreset)
  } catch {
    /* ignore */
  }
  return [...DEFAULT_SSH_PRESETS]
}
