<template>
  <section class="panel">
    <div class="panel-head">
      <h2>🌐 全局分支设置</h2>
      <span class="head-count">应用到全部工程</span>
    </div>
    <div class="panel-body">
      <div class="gp-presets">
        <div class="gp-presets-head">
          <span>Git 地址配置预设</span>
          <el-button size="small" text :disabled="merge.busy" @click="openPresetCreateDialog">
            新增
          </el-button>
        </div>
        <el-radio-group v-model="store.activeSshPreset" class="gp-preset-list" @change="store.applySshPreset">
          <label
            v-for="preset in store.sshPresets"
            :key="preset.id"
            class="gp-preset-item"
          >
            <el-radio :value="preset.id" />
            <div class="gp-preset-main" @click="store.applySshPreset(preset.id)">
              <span class="gp-preset-name">{{ preset.name }}</span>
              <span class="gp-preset-host">{{ protocolLabel(preset.origin) }}</span>
              <span class="gp-preset-host">{{ formatPresetVar(preset.variable) }}</span>
              <span v-if="preset.host || preset.port" class="gp-preset-host">{{ preset.host }}{{ preset.port ? `:${preset.port}` : '' }}</span>
              <span class="gp-preset-host">{{ preset.origin }}</span>
            </div>
            <div class="gp-preset-actions">
              <el-button
                size="small"
                text
                :disabled="merge.busy"
                @click.stop="openPresetEditDialog(preset)"
              >
                编辑
              </el-button>
              <el-button
                size="small"
                text
                :disabled="merge.busy || store.sshPresets.length <= 1"
                @click.stop="store.removeSshPreset(preset.id)"
              >
                删除
              </el-button>
            </div>
          </label>
        </el-radio-group>
      </div>

      <div class="gp-batch-ssh">
        <div>
          <div class="gp-batch-title">批量修改 Git 地址</div>
          <div class="gp-batch-sub">已勾选 {{ checkedCount }} 个工程</div>
        </div>
        <el-button
          type="primary"
          plain
          :disabled="!checkedCount || merge.busy"
          @click="openBatchSshDialog"
        >
          修改
        </el-button>
      </div>

      <div class="gp-grid gp-env-grid">
        <div class="gp-field">
          <label>全局 Git 地址前缀</label>
          <el-input
            v-model="store.global.ssh_origin"
            placeholder="例如 ssh://git@38.76.216.46:42221 或 https://gitlab.example.com"
            :disabled="merge.busy"
          />
        </div>
      </div>

      <div class="gp-grid">
        <div class="gp-field">
          <label>全局源分支（可输入或下拉选择）</label>
          <el-select
            v-model="store.global.source_branch"
            filterable
            allow-create
            default-first-option
            placeholder="如：feature-20260630"
            :disabled="merge.busy"
          >
            <el-option v-for="b in store.globalBranches" :key="b" :label="b" :value="b" />
          </el-select>
        </div>
        <div class="gp-field">
          <label>全局目标分支（可多选 / 搜索 / 自定义）</label>
          <el-select
            v-model="store.global.target_branches"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="搜索分支并添加"
            :disabled="merge.busy"
          >
            <el-option v-for="b in store.globalBranches" :key="b" :label="b" :value="b" />
          </el-select>
        </div>
      </div>

      <div class="gp-foot">
        <el-input
          v-model="store.global.ssh_host"
          placeholder="（可选）Git 地址 —— 点击「加载分支」时需要"
          :disabled="merge.busy"
        />
        <el-button
          :loading="branchLoading || store.globalBranchesLoading"
          :disabled="merge.busy"
          @click="loadBranches"
        >
          ⟳ 加载分支
        </el-button>
        <el-button :disabled="merge.busy" @click="store.applyGlobalSource">应用源分支</el-button>
        <el-button :disabled="merge.busy" @click="store.applyGlobalTargets">应用目标分支</el-button>
        <el-button type="primary" :disabled="merge.busy" @click="store.applyGlobalAll">
          一键应用到全部
        </el-button>
      </div>
    </div>
    <el-dialog
      v-model="batchSshVisible"
      :title="batchSshDialogTitle"
      width="560px"
      append-to-body
      class="batch-ssh-dialog"
      :z-index="2600"
      :close-on-click-modal="false"
    >
      <div class="batch-ssh-form">
        <div class="batch-ssh-tip">{{ batchSshDialogTip }}</div>
        <div v-if="batchSshMode === 'batch'" class="batch-ssh-presets">
          <div class="batch-ssh-presets-head">
            <span>Git 地址配置</span>
            <el-button size="small" text :disabled="merge.busy" @click="saveBatchSshPreset">
              保存为新配置
            </el-button>
          </div>
          <el-select
            v-model="store.activeSshPreset"
            placeholder="选择 Git 地址配置预设"
            @change="selectBatchSshPreset"
          >
            <el-option
              v-for="preset in store.sshPresets"
              :key="preset.id"
              :label="preset.name"
              :value="preset.id"
            >
              <div class="batch-preset-option">
                <span class="batch-preset-name">{{ preset.name }}</span>
                <span class="batch-preset-meta">{{ formatPresetVar(preset.variable) }}</span>
                <span class="batch-preset-meta">{{ preset.origin }}</span>
              </div>
            </el-option>
          </el-select>
        </div>
        <label>配置名称</label>
        <el-input v-model="batchSshForm.name" placeholder="例如 外网 GitLab" />
        <label>变量名</label>
        <el-input v-model="batchSshForm.variable" placeholder="例如 ssh_origin 或 gitlab_outer" />
        <label>Git 地址前缀</label>
        <el-input v-model="batchSshForm.origin" placeholder="例如 ssh://git@38.76.216.46:42221 或 https://gitlab.example.com" />
      </div>
      <template #footer>
        <el-button @click="batchSshVisible = false">取消</el-button>
        <el-button
          v-if="batchSshMode === 'batch'"
          :loading="batchSshSaving"
          @click="savePresetFromForm"
        >
          保存配置
        </el-button>
        <el-button type="primary" :loading="batchSshSaving" @click="submitSshDialog">
          {{ batchSshMode === 'batch' ? '保存并应用' : '保存配置' }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useProjectsStore } from '../stores/projects'
import { useMergeStore } from '../stores/merge'
import { api } from '../api'
import { buildGitRemoteWithOriginVar, formatGitRemoteVar, normalizeGitRemoteVarName } from '../utils/gitRemote'

const store = useProjectsStore()
const merge = useMergeStore()
const branchLoading = ref(false)
const batchSshVisible = ref(false)
const batchSshSaving = ref(false)
const batchSshMode = ref('batch')
const editingPresetId = ref('')
const batchSshForm = reactive({ name: '', variable: 'ssh_origin', host: '', port: '', origin: '' })
const checkedCount = computed(() => store.projects.filter((p) => p.checked).length)
const activeBatchSshPreset = computed(() => store.sshPresets.find((x) => x.id === store.activeSshPreset))
const batchSshDialogTitle = computed(() => {
  if (batchSshMode.value === 'create') return '新增 Git 地址配置'
  if (batchSshMode.value === 'edit') return '编辑 Git 地址配置'
  return '批量修改 Git 地址'
})
const batchSshDialogTip = computed(() => (
  batchSshMode.value === 'batch'
    ? '选择一组 Git 地址配置，应用到已勾选工程，并同步设置地址前缀'
    : '维护 Git 地址配置名称、变量名和实际地址；卡片应用变量会使用这里的配置'
))

function originProtocol(origin) {
  if (/^https?:\/\//i.test(origin || '')) return 'https'
  if (/^ssh:\/\//i.test(origin || '')) return 'ssh'
  return ''
}

async function loadBranches() {
  branchLoading.value = true
  try {
    await merge.runWithCommandLog(() => store.loadGlobalBranches())
  } catch (e) {
    console.error(e)
  } finally {
    branchLoading.value = false
  }
}

function validateGitOrigin(origin) {
  if (!origin) return '请填写地址前缀'
  if (!originProtocol(origin)) return '地址前缀仅支持 ssh://、http:// 或 https://'
  return ''
}

function validateVariableName(variable) {
  const clean = normalizeGitRemoteVarName(variable)
  if (!clean) return '请填写变量名'
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(clean)) return '变量名只能包含字母、数字、下划线，且不能以数字开头'
  return ''
}

function formatPresetVar(variable) {
  return formatGitRemoteVar(variable)
}

function protocolLabel(origin) {
  return /^https?:\/\//i.test(origin || '') ? 'HTTPS' : 'SSH'
}

function fillBatchSshForm(preset) {
  if (preset) {
    batchSshForm.name = preset.name || ''
    batchSshForm.variable = preset.variable || 'ssh_origin'
    batchSshForm.host = preset.host || ''
    batchSshForm.port = preset.port || ''
    batchSshForm.origin = preset.origin || ''
    return
  }
  const origin = store.global.ssh_origin || 'ssh://git@38.76.216.46:42221'
  batchSshForm.name = hostPortFromOrigin(origin) || origin
  batchSshForm.variable = 'ssh_origin'
  batchSshForm.host = ''
  batchSshForm.port = ''
  batchSshForm.origin = origin
}

function selectBatchSshPreset(id) {
  const preset = store.sshPresets.find((x) => x.id === id)
  if (!preset) return
  fillBatchSshForm(preset)
  store.activeSshPreset = id
  store.saveSshPresets()
}

function openBatchSshDialog() {
  batchSshMode.value = 'batch'
  editingPresetId.value = ''
  const preset = activeBatchSshPreset.value || store.sshPresets[0]
  if (preset) {
    store.activeSshPreset = preset.id
    fillBatchSshForm(preset)
    store.saveSshPresets()
  } else {
    fillBatchSshForm(null)
  }
  batchSshVisible.value = true
}

function openPresetCreateDialog() {
  batchSshMode.value = 'create'
  editingPresetId.value = ''
  fillBatchSshForm(null)
  batchSshVisible.value = true
}

function openPresetEditDialog(preset) {
  batchSshMode.value = 'edit'
  editingPresetId.value = preset.id
  fillBatchSshForm(preset)
  batchSshVisible.value = true
}

function readSshForm() {
  const host = batchSshForm.host.trim()
  const port = batchSshForm.port.trim()
  const variable = normalizeGitRemoteVarName(batchSshForm.variable)
  const variableError = validateVariableName(variable)
  if (variableError) {
    ElMessage.error(variableError)
    return null
  }
  const origin = batchSshForm.origin.trim().replace(/\/+$/, '')
  const originError = validateGitOrigin(origin)
  if (originError) {
    ElMessage.error(originError)
    return null
  }
  const name = (batchSshForm.name || hostPortFromOrigin(origin) || origin).trim()
  return { name, variable, host, port, origin }
}

function hostPortFromOrigin(origin) {
  try {
    const u = new URL(origin)
    return u.host || ''
  } catch {
    const m = String(origin || '').match(/^ssh:\/\/(?:[^@]+@)?([^/]+)$/i)
    return m ? m[1] : ''
  }
}

function savePresetFromForm() {
  const data = readSshForm()
  if (!data) return null
  let preset
  if (batchSshMode.value === 'edit' && editingPresetId.value) {
    preset = store.updateSshPreset(editingPresetId.value, data)
    if (preset) store.applySshPreset(preset.id)
  } else {
    preset = store.addSshPreset(data.name, data.host, data.port, data.origin, data.variable)
  }
  if (!preset) return null
  fillBatchSshForm(preset)
  ElMessage.success(`已保存 Git 地址配置「${preset.name}」`)
  return preset
}

function saveBatchSshPreset() {
  const mode = batchSshMode.value
  const editingId = editingPresetId.value
  batchSshMode.value = 'create'
  editingPresetId.value = ''
  const preset = savePresetFromForm()
  batchSshMode.value = mode
  editingPresetId.value = editingId
  return preset
}

async function submitSshDialog() {
  if (batchSshMode.value !== 'batch') {
    if (savePresetFromForm()) batchSshVisible.value = false
    return
  }
  await applyBatchSsh()
}

async function applyBatchSsh() {
  const data = readSshForm()
  if (!data) return
  const { name, variable, host, port, origin } = data
  const selected = store.projects.filter((p) => p.checked)
  if (!selected.length) {
    ElMessage.warning('请先勾选要修改的工程')
    return
  }
  const changes = selected.map((p) => ({
    id: p.id,
    name: p.name || p.project_path || p.ssh_host || '未命名工程',
    before: p.ssh_host,
    after: buildGitRemoteWithOriginVar(p.ssh_host, p.project_path, origin),
  })).filter((c) => c.after && c.after !== c.before)
  if (!changes.length) {
    ElMessage.warning('没有可修改的 Git 地址')
    return
  }
  batchSshSaving.value = true
  const beforeGlobal = { ...store.global }
  try {
    store.global.ssh_origin = origin
    store.global.ssh_vars = { ...(store.global.ssh_vars || {}), [variable]: origin }
    if (store.activeSshPreset) {
      store.updateSshPreset(store.activeSshPreset, {
        name,
        variable,
        host,
        port,
        origin,
      })
    }
    changes.forEach((c) => {
      const p = store.projects.find((x) => x.id === c.id)
      if (p) {
        p.ssh_host = c.after
        p.branches = []
      }
    })
    await store.save()
    await api.auditLog({
      action: 'project_ssh_update',
      title: '批量修改 Git 地址',
      detail: `批量修改 ${changes.length} 个工程 Git 地址前缀为 ${origin}`,
      payload: { host, port, origin, variable, changes },
    })
    batchSshVisible.value = false
    ElMessage.success(`已修改 ${changes.length} 个工程 Git 地址`)
  } catch (e) {
    changes.forEach((c) => {
      const p = store.projects.find((x) => x.id === c.id)
      if (p) p.ssh_host = c.before
    })
    store.global = beforeGlobal
    ElMessage.error('批量修改失败：' + e.message)
  } finally {
    batchSshSaving.value = false
  }
}
</script>
