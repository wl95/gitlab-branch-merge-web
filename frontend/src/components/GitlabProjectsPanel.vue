<template>
  <section class="panel gitlab-panel">
    <div class="panel-head">
      <h2>远程 GitLab 工程</h2>
      <el-button
        v-if="allRepos.length"
        size="small"
        plain
        @click="cloneConfigOpen = true"
      >
        拉取配置
      </el-button>
    </div>
    <div class="panel-body">
      <div class="gitlab-fields">
        <el-input
          v-model="store.gitlabUrl"
          placeholder="GitLab 项目页地址"
          clearable
          @keyup.enter="load"
        />
        <el-input
          v-model="store.gitlabToken"
          placeholder="Private Token，Your projects 必填"
          type="password"
          show-password
          clearable
          @keyup.enter="load"
        />
        <el-segmented
          v-model="store.gitlabScope"
          :options="scopeOptions"
          block
        />
        <div class="gitlab-actions">
          <el-checkbox v-model="store.gitlabIncludeBranches">
            同步分支
          </el-checkbox>
          <div class="gitlab-action-buttons">
            <el-button :loading="store.gitlabDiagnosing" plain @click="diagnose">
              诊断
            </el-button>
            <el-button
              v-if="store.gitlabDiagnosis"
              plain
              @click="diagnosisExpanded = !diagnosisExpanded"
            >
              <el-icon>
                <ArrowUp v-if="diagnosisExpanded" />
                <ArrowDown v-else />
              </el-icon>
              <span>{{ diagnosisExpanded ? '收起诊断' : '展开诊断' }}</span>
            </el-button>
            <el-button type="primary" :loading="store.gitlabLoading" @click="load">
              获取
            </el-button>
          </div>
        </div>
      </div>
      <div class="scan-hint">
        远程工程只用于拉取到本地；需要合并、Pick 或查看 diff 时，请从本地仓库扫描加入工程配置。
      </div>

      <div v-show="store.gitlabShow" class="scan-list">
        <div v-if="store.gitlabDiagnosis" class="gitlab-diagnosis">
          <button
            type="button"
            class="gitlab-diagnosis-head"
            @click="diagnosisExpanded = !diagnosisExpanded"
          >
            <span>{{ diagnosisTitle }}</span>
            <strong>{{ diagnosisSummary }}</strong>
            <span class="gitlab-diagnosis-toggle">
              {{ diagnosisExpanded ? '收起' : '展开' }}
              <el-icon :class="{ expanded: diagnosisExpanded }"><ArrowDown /></el-icon>
            </span>
          </button>
          <div v-show="diagnosisExpanded" class="gitlab-diagnosis-body">
            <div v-if="store.gitlabDiagnosis.user" class="gitlab-diagnosis-user">
              当前用户：{{ store.gitlabDiagnosis.user.username || store.gitlabDiagnosis.user.name || store.gitlabDiagnosis.user.id }}
            </div>
            <div
              v-for="check in store.gitlabDiagnosis.checks || []"
              :key="check.name"
              :class="['gitlab-diagnosis-row', { fail: !check.ok }]"
            >
              <span>{{ check.name }}</span>
              <strong>{{ formatCheckValue(check) }}</strong>
              <em v-if="check.error">{{ check.error }}</em>
            </div>
          </div>
        </div>

        <div v-if="store.gitlabLoading" class="scan-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          正在获取 GitLab 工程…
        </div>

        <template v-else-if="store.gitlabResult">
          <div class="scan-list-fixed">
            <div v-if="store.gitlabResult.warnings && store.gitlabResult.warnings.length" class="scan-empty warn">
              <div v-for="(w, i) in store.gitlabResult.warnings" :key="i">{{ w }}</div>
            </div>

            <el-input
              v-if="allRepos.length"
              v-model="keyword"
              class="scan-filter"
              placeholder="按工程名称、路径或 SSH 地址筛选"
              clearable
            />

            <div v-if="repos.length" class="scan-checkall">
              <el-checkbox
                :model-value="allSelected"
                :indeterminate="someSelected"
                @change="toggleAll"
              >
                全选
              </el-checkbox>
              <span>{{ countText }}</span>
              <el-button
                size="small"
                type="primary"
                plain
                :loading="batchPulling"
                :disabled="!selectedRepos.length"
                @click.stop="pullSelected"
              >
                拉取已选
              </el-button>
            </div>

            <div v-if="!repos.length && !store.gitlabResult.warnings?.length" class="scan-empty">
              {{ allRepos.length ? '没有匹配的工程' : '没有获取到工程' }}
            </div>
          </div>

          <div class="scan-list-body">
            <div
              v-for="repo in repos"
              :key="repo.id || repo.ssh_host || repo.project_path"
              :class="['scan-item', 'gitlab-repo-item', { selected: selected(repo) }]"
              @click="toggleSelected(repo)"
            >
              <el-checkbox :model-value="selected(repo)" @click.stop @change="() => toggleSelected(repo)" />
              <div class="gitlab-project-main">
                <div class="scan-host">{{ repo.project_path || repo.name }}</div>
                <div class="scan-path">{{ repo.ssh_host || repo.http_url || repo.web_url }}</div>
                <div v-if="repo.branches?.length" class="gitlab-branches">
                  {{ repo.branches.length }} 个分支
                </div>
                <div v-if="pullStatus[repoKey(repo)]" :class="['gitlab-pull-status', { fail: !pullStatus[repoKey(repo)].ok }]">
                  {{ pullStatus[repoKey(repo)].message }}
                </div>
              </div>
              <el-button
                size="small"
                type="primary"
                plain
                :loading="!!pulling[repoKey(repo)]"
                :disabled="repoExistsLocally(repo)"
                @click.stop="pullRepo(repo)"
              >
                {{ repoExistsLocally(repo) ? '已存在' : '拉取' }}
              </el-button>
            </div>
          </div>
        </template>
      </div>
    </div>
  </section>

  <el-dialog
    v-model="cloneConfigOpen"
    title="拉取配置"
    width="640px"
    class="gitlab-clone-dialog"
  >
    <div class="gitlab-clone-config">
      <div class="gitlab-clone-title">
        <span>远程工程拉取设置</span>
        <em>{{ cloneProtocolLabel }}</em>
      </div>
      <div class="gitlab-clone-field">
        <label>本地目录</label>
        <el-input
          v-model="cloneBaseDir"
          placeholder="例如 /Users/me/projects，系统会自动创建仓库子目录"
          clearable
        />
      </div>
      <div class="gitlab-clone-field">
        <label>配置预设</label>
        <div class="gitlab-preset-list">
          <button
            v-for="preset in store.sshPresets"
            :key="preset.id"
            type="button"
            :class="['gitlab-preset-chip', { active: preset.id === selectedPresetId }]"
            @click="applyPreset(preset.id)"
          >
            <span>{{ preset.name }}</span>
            <em>{{ formatPresetVar(preset.variable) }} · {{ preset.origin }}</em>
          </button>
        </div>
      </div>
      <div class="gitlab-clone-field">
        <label>Git 地址前缀</label>
        <el-input
          v-model="cloneOrigin"
          placeholder="由配置预设带入，例如 ssh://git@192.168.12.213:2221 或 http://192.168.12.213:4481"
          clearable
        />
      </div>
      <div class="gitlab-clone-preview">
        {{ clonePreview }}
      </div>
    </div>
    <template #footer>
      <div class="gitlab-clone-dialog-foot">
        <span>{{ selectedRepos.length ? `已选 ${selectedRepos.length} 个工程` : '先在远程列表勾选工程' }}</span>
        <el-button @click="cloneConfigOpen = false">关闭</el-button>
        <el-button
          type="primary"
          :loading="batchPulling"
          :disabled="!selectedRepos.length"
          @click="pullSelected"
        >
          拉取已选
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'
import { useMergeStore } from '../stores/merge'
import { api } from '../api'
import { buildGitRemoteWithOriginVar, formatGitRemoteVar } from '../utils/gitRemote'

const store = useProjectsStore()
const merge = useMergeStore()
const keyword = ref('')
const diagnosisExpanded = ref(false)
const cloneBaseDir = ref(store.scanFolderPath || './repos')
const selectedPresetId = ref(store.activeSshPreset || '')
const cloneProtocol = ref('ssh')
const cloneOrigin = ref('')
const cloneConfigOpen = ref(false)
const selectedKeys = ref([])
const pulling = reactive({})
const pullStatus = reactive({})
const batchPulling = ref(false)
const scopeOptions = [
  { label: 'Your projects', value: 'membership' },
  { label: 'Explore projects', value: 'all' },
]
const allRepos = computed(() => (store.gitlabResult ? store.gitlabResult.projects : []))
const repos = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return allRepos.value
  return allRepos.value.filter((repo) => {
    const text = [
      repo.name,
      repo.project_path,
      repo.path,
      repo.ssh_host,
      repo.http_url,
      repo.web_url,
    ].filter(Boolean).join(' ').toLowerCase()
    return text.includes(kw)
  })
})
const countText = computed(() => {
  if (!keyword.value.trim()) return `发现 ${allRepos.value.length} 个工程`
  return `匹配 ${repos.value.length} / ${allRepos.value.length} 个工程`
})
const selectedRepos = computed(() => repos.value.filter((r) => selected(r)))
const allSelected = computed(() => repos.value.length > 0 && repos.value.every((r) => selected(r)))
const someSelected = computed(() => repos.value.some((r) => selected(r)))
const diagnosisChecks = computed(() => store.gitlabDiagnosis?.checks || [])
const selectedPreset = computed(() => store.sshPresets.find((x) => x.id === selectedPresetId.value) || store.sshPresets[0])
const cloneProtocolLabel = computed(() => /^https?:\/\//i.test(normalizedCloneOrigin.value) ? 'HTTPS' : 'SSH')
const clonePreview = computed(() => {
  const first = repos.value[0]
  const remote = first ? remoteForClone(first) : normalizedCloneOrigin.value
  return remote ? `示例：${remote}` : '请设置拉取地址前缀'
})
const normalizedCloneOrigin = computed(() => (cloneOrigin.value || '').trim().replace(/\/+$/, ''))
const diagnosisTitle = computed(() => {
  const user = store.gitlabDiagnosis?.user
  if (!user) return '诊断结果'
  return `诊断结果 · ${user.username || user.name || user.id}`
})
const diagnosisSummary = computed(() => {
  const checks = diagnosisChecks.value
  if (!checks.length) return '暂无检查项'
  const ok = checks.filter((x) => x.ok).length
  const fail = checks.length - ok
  return fail ? `${ok} 通过 / ${fail} 失败` : `${ok} 项通过`
})

cloneOrigin.value = selectedPreset.value?.origin || store.global.ssh_origin || ''

watch(
  () => [store.activeSshPreset, store.sshPresets.length],
  () => {
    if (store.activeSshPreset) selectedPresetId.value = store.activeSshPreset
    const preset = store.sshPresets.find((x) => x.id === selectedPresetId.value) || store.sshPresets[0]
    if (preset?.origin) {
      cloneProtocol.value = /^https?:\/\//i.test(preset.origin) ? 'https' : 'ssh'
      cloneOrigin.value = preset.origin
    }
  }
)

function repoKey(repo) {
  return String(repo.id || repo.ssh_host || repo.project_path || repo.name || '')
}

function selected(repo) {
  return selectedKeys.value.includes(repoKey(repo))
}

function toggleSelected(repo) {
  const key = repoKey(repo)
  if (!key) return
  selectedKeys.value = selected(repo)
    ? selectedKeys.value.filter((x) => x !== key)
    : [...selectedKeys.value, key]
}

function toggleAll(val) {
  if (val) {
    const set = new Set(selectedKeys.value)
    repos.value.forEach((r) => {
      const key = repoKey(r)
      if (key) set.add(key)
    })
    selectedKeys.value = [...set]
  } else {
    const remove = new Set(repos.value.map(repoKey))
    selectedKeys.value = selectedKeys.value.filter((x) => !remove.has(x))
  }
}

function load() {
  store.loadGitlabProjects()
}

function diagnose() {
  diagnosisExpanded.value = false
  store.diagnoseGitlabProjects()
}

function formatPresetVar(variable) {
  return formatGitRemoteVar(variable)
}

function applyPreset(id) {
  if (!id) return
  store.applySshPreset(id)
  const preset = store.sshPresets.find((x) => x.id === id)
  if (preset?.origin) {
    cloneProtocol.value = /^https?:\/\//i.test(preset.origin) ? 'https' : 'ssh'
    cloneOrigin.value = preset.origin
  }
}

function remoteForClone(repo) {
  const origin = normalizedCloneOrigin.value || defaultCloneOrigin(repo)
  const path = repo.project_path || repo.path || repo.name || ''
  if (!origin || !path) return repo.ssh_host || repo.http_url || repo.web_url || ''
  return buildGitRemoteWithOriginVar('', path, origin)
}

function repoFolderName(repo) {
  const path = String(repo.project_path || repo.path || repo.name || '').replace(/\.git$/, '').replace(/\/+$/, '')
  return path.split('/').filter(Boolean).pop() || ''
}

function targetRepoDir(repo) {
  const base = cloneBaseDir.value.trim().replace(/\/+$/, '')
  const name = repoFolderName(repo)
  return base && name ? `${base}/${name}` : ''
}

function repoExistsLocally(repo) {
  const target = targetRepoDir(repo)
  return !!target && store.projects.some((p) => (p.local_dir || '').replace(/\/+$/, '') === target)
}

function defaultCloneOrigin(repo) {
  if (cloneProtocol.value === 'https') {
    const url = repo.http_url || repo.web_url || store.gitlabUrl
    try {
      const u = new URL(url)
      return `${u.protocol}//${u.host}`
    } catch {
      return ''
    }
  }
  return selectedPreset.value?.origin || store.global.ssh_origin || ''
}

async function pullRepo(repo) {
  if (repoExistsLocally(repo)) {
    ElMessage.warning('该工程本地目录已存在，无需重复拉取')
    return
  }
  const key = repoKey(repo)
  const localDir = cloneBaseDir.value.trim()
  if (!localDir) {
    ElMessage.error('请先填写拉取到本地目录')
    return
  }
  const sshHost = remoteForClone(repo)
  if (!sshHost) {
    ElMessage.error('该工程缺少可拉取地址')
    return
  }
  pulling[key] = true
  pullStatus[key] = { ok: true, message: '正在拉取...' }
  try {
    const r = await merge.runWithCommandLog(() => api.projectPull({
      name: repo.name || repo.project_path,
      ssh_host: sshHost,
      project_path: repo.project_path,
      local_dir: localDir,
      global: { ...store.global },
    }), { reveal: false })
    pullStatus[key] = { ok: true, message: `已拉取到 ${r.local_dir}` }
    ElMessage.success(`已拉取 ${repo.project_path || repo.name}`)
  } catch (e) {
    pullStatus[key] = { ok: false, message: `拉取失败：${e.message}` }
    ElMessage.error(`拉取失败：${e.message}`)
  } finally {
    pulling[key] = false
  }
}

async function pullSelected() {
  if (!selectedRepos.value.length) return
  batchPulling.value = true
  try {
    const pendingRepos = selectedRepos.value.filter((repo) => !repoExistsLocally(repo))
    if (!pendingRepos.length) {
      ElMessage.warning('已选工程本地目录都已存在，无需拉取')
      return
    }
    for (const repo of pendingRepos) {
      await pullRepo(repo)
    }
  } finally {
    batchPulling.value = false
  }
}

function formatCheckValue(check) {
  if (!check.ok) return '失败'
  if (typeof check.count === 'number') return `${check.count} 个`
  if (check.version) return check.version
  if (check.user) return check.user.username || check.user.name || String(check.user.id || '成功')
  return '成功'
}
</script>
