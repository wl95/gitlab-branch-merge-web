<template>
  <el-dialog
    :model-value="modelValue"
    width="960"
    top="6vh"
    :close-on-click-modal="false"
    class="bm-dialog"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="bm-header">
        <el-icon class="bm-ico"><Operation /></el-icon>
        <div class="bm-title">批量分支管理</div>
        <div class="bm-sub">对多个工程同时创建 / 删除 / 重命名远程分支，或切换本地工作区分支</div>
      </div>
    </template>

    <div class="bm-body">
      <!-- 工程选择 -->
      <div class="bm-sec">
        <div class="bm-sec-head">
          <span class="bm-sec-label">目标工程</span>
          <span class="bm-sec-count">已选 {{ checkedCount }} / {{ candidates.length }}</span>
          <div class="bm-sec-actions">
            <el-button text size="small" :disabled="!candidates.length" @click="checkAll">全选</el-button>
            <el-button text size="small" :disabled="!checkedCount" @click="uncheckAll">清空</el-button>
          </div>
        </div>
        <div v-if="!candidates.length" class="bm-empty">
          {{ emptyText }}
        </div>
        <div v-else class="bm-proj-list">
          <div
            v-for="p in candidates"
            :key="p.id"
            class="bm-proj"
            :class="{ active: checkedIds.has(p.id) }"
            @click="toggle(p)"
          >
            <el-checkbox :model-value="checkedIds.has(p.id)" @click.stop="toggle(p)" />
            <span class="bm-proj-name">{{ p.name || p.ssh_host }}</span>
            <span class="bm-proj-host">{{ p.ssh_host }}</span>
          </div>
        </div>
      </div>

      <!-- 操作类型 -->
      <el-tabs v-model="tab" class="bm-tabs">
        <el-tab-pane label="创建分支" name="create">
          <div class="bm-form">
            <div class="bm-field">
              <label>新分支名（可多个）</label>
              <div class="bm-field-row">
                <el-button
                  :icon="EditPen"
                  title="批量编辑新分支名"
                  @click="openCreateNamesEditor"
                />
                <el-select
                  v-model="createNames"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  :reserve-keyword="false"
                  placeholder="输入分支名后按回车或逗号添加，可添加多个"
                  style="flex: 1"
                >
                  <el-option v-for="b in allBranches" :key="b" :label="b" :value="b" />
                </el-select>
              </div>
              <div class="bm-field-hint">
                可输入多个分支名，每个分支都将基于所选目标分支创建；留空目标分支则使用各工程源分支
              </div>
            </div>
            <div class="bm-field">
              <label>目标分支（基于）</label>
              <div class="bm-field-row">
                <el-select
                  v-model="createFrom"
                  filterable
                  clearable
                  :loading="loadingBranches"
                  :placeholder="selectPlaceholder"
                  style="flex: 1"
                >
                  <el-option v-for="b in allBranches" :key="b" :label="b" :value="b" />
                </el-select>
                <el-button
                  :icon="Refresh"
                  :loading="loadingBranches"
                  title="重新加载分支"
                  @click="loadAllBranches"
                >
                  刷新
                </el-button>
              </div>
              <div class="bm-field-hint">
                自动加载所选工程的全部分支，新分支将基于所选分支创建；留空则使用各工程源分支
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="删除分支" name="delete">
          <div class="bm-form">
            <div class="bm-field">
              <label>要删除的分支名（可多个）</label>
              <div class="bm-field-row">
                <el-button
                  :icon="EditPen"
                  title="批量编辑要删除的分支名"
                  @click="openNamesEditor('delete')"
                />
                <el-select
                  v-model="deleteNames"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  :reserve-keyword="false"
                  placeholder="输入分支名后按回车或逗号添加，可添加多个"
                  style="flex: 1"
                >
                  <el-option v-for="b in allBranches" :key="b" :label="b" :value="b" />
                </el-select>
              </div>
            </div>
            <div class="bm-tip danger">
              将删除所选工程上的远程分支。受保护分支（master / main / develop / release 等）禁止删除。
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="重命名分支" name="rename">
          <div class="bm-form">
            <div class="bm-field">
              <label>原分支名</label>
              <el-input v-model="oldName" placeholder="例如：feature/old-name" @keyup.enter="run" />
            </div>
            <div class="bm-field">
              <label>新分支名</label>
              <div class="bm-field-row">
                <el-button
                  :icon="EditPen"
                  title="编辑新分支名"
                  @click="openNamesEditor('rename')"
                />
                <el-input
                  v-model="newName"
                  placeholder="例如：feature/new-name"
                  @keyup.enter="run"
                />
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="切换本地分支" name="switchLocal">
          <div class="bm-form">
            <div class="bm-field">
              <label>批量设置切换分支</label>
              <div class="bm-field-row">
                <el-select
                  v-model="switchLocalName"
                  filterable
                  allow-create
                  default-first-option
                  clearable
                  :loading="loadingBranches"
                  :placeholder="selectPlaceholder"
                  style="flex: 1"
                >
                  <el-option v-for="b in allBranches" :key="b" :label="b" :value="b" />
                </el-select>
                <el-button :disabled="!switchLocalNameText" @click="applySwitchLocalNameToAll">
                  应用到已选
                </el-button>
                <el-button
                  :icon="Refresh"
                  :loading="loadingBranches"
                  title="重新加载分支"
                  @click="loadAllBranches"
                >
                  刷新
                </el-button>
              </div>
              <div class="bm-field-hint">
                默认使用每个工程卡片当前选中的源分支；可逐个调整，也可批量设置为相同分支。仅切换本地仓库当前分支，不会 reset 或 push。
              </div>
            </div>
            <div class="bm-switch-list">
              <div v-if="!selectedProjects.length" class="bm-empty small">
                请先在上方选择要切换的本地工程
              </div>
              <div v-for="p in selectedProjects" :key="p.id" class="bm-switch-item">
                <div class="bm-switch-main">
                  <span class="bm-switch-name">{{ p.name || p.project_path || p.local_dir }}</span>
                  <span class="bm-switch-dir">{{ p.local_dir }}</span>
                </div>
                <el-select
                  v-model="switchLocalBranches[p.id]"
                  filterable
                  allow-create
                  default-first-option
                  clearable
                  placeholder="选择该工程要切换到的分支"
                >
                  <el-option
                    v-for="b in projectBranchOptions(p)"
                    :key="`${p.id}-${b}`"
                    :label="b"
                    :value="b"
                  />
                </el-select>
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>

      <!-- 执行 -->
      <div class="bm-actions">
        <el-button
          type="primary"
          :loading="running"
          :disabled="!checkedCount"
          @click="run"
        >
          {{ runLabel }}
        </el-button>
        <el-button
          v-if="branchUndo && branchUndo.has_undo"
          type="danger"
          plain
          :loading="undoingBranch"
          :disabled="running"
          @click="undoBranchOperation"
        >
          {{ undoButtonText }}
        </el-button>
        <span class="bm-note">将依次对 {{ checkedCount }} 个工程执行，并逐工程报告结果</span>
      </div>

      <div v-if="branchUndo && branchUndo.has_undo" class="bm-undo-tip">
        最近{{ undoActionText }}于 {{ branchUndo.created_at }}，共 {{ branchUndo.items.length }} 个分支可撤回
      </div>

      <div v-if="branchLogs.length" class="bm-live">
        <div class="bm-live-head">实时执行命令</div>
        <div class="bm-live-list">
          <div v-for="l in branchLogs" :key="l.id" class="bm-live-line" :class="l.cls">
            {{ l.text }}
          </div>
        </div>
      </div>

      <!-- 结果 -->
      <div v-if="results.length" class="bm-results">
        <div class="bm-res-head">
          执行结果
          <span class="bm-ok">成功 {{ okCount }}</span>
          <span class="bm-fail">失败 {{ failCount }}</span>
        </div>
        <div class="bm-res-list">
          <div v-for="(r, i) in results" :key="i" class="bm-res" :class="r.ok ? 'ok' : 'fail'">
            <el-icon class="bm-res-ico">
              <CircleCheckFilled v-if="r.ok" />
              <CircleCloseFilled v-else />
            </el-icon>
            <div class="bm-res-main">
              <div class="bm-res-line">
                <span class="bm-res-name">{{ r.name }}</span>
                <span class="bm-res-msg">{{ r.ok ? r.message : r.error }}</span>
              </div>
              <div v-if="r.commands && r.commands.length" class="bm-res-commands">
                <div v-for="cmd in r.commands" :key="cmd" class="bm-res-command">{{ cmd }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 撤回本次操作 -->
      <div v-if="lastUndo" class="bm-undo">
        <el-button type="warning" plain :loading="undoing" @click="undoRun">
          <el-icon style="margin-right: 4px"><RefreshLeft /></el-icon>
          撤回本次{{ actionLabel }}操作
        </el-button>
        <span class="bm-undo-note">
          将自动执行逆向操作（创建→删除、删除→恢复原提交、重命名→改回原名），并实时报告结果
        </span>
      </div>
      <div v-if="undoResults.length" class="bm-results">
        <div class="bm-res-head">
          撤回结果
          <span class="bm-ok">成功 {{ undoOkCount }}</span>
          <span class="bm-fail">失败 {{ undoFailCount }}</span>
        </div>
        <div class="bm-res-list">
          <div v-for="(r, i) in undoResults" :key="i" class="bm-res" :class="r.ok ? 'ok' : 'fail'">
            <el-icon class="bm-res-ico">
              <CircleCheckFilled v-if="r.ok" />
              <CircleCloseFilled v-else />
            </el-icon>
            <span class="bm-res-name">{{ r.name }}</span>
            <span class="bm-res-msg">{{ r.ok ? r.message : r.error }}</span>
          </div>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="namesEditorVisible"
      :title="namesEditorTitle"
      width="560"
      append-to-body
      class="bm-names-dialog"
    >
      <el-input
        v-model="namesDraft"
        type="textarea"
        :rows="10"
        resize="vertical"
        placeholder="每行一个分支名，也支持逗号或空格分隔"
      />
      <template #footer>
        <el-button @click="namesEditorVisible = false">取消</el-button>
        <el-button type="primary" @click="applyNamesDraft">确定</el-button>
      </template>
    </el-dialog>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Operation,
  Refresh,
  EditPen,
  CircleCheckFilled,
  CircleCloseFilled,
} from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'
import { useMergeStore } from '../stores/merge'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const projects = useProjectsStore()
const merge = useMergeStore()

const tab = ref('create')
const running = ref(false)
const undoingBranch = ref(false)
const results = ref([])
const branchUndo = ref(null)
const branchLogs = ref([])
const branchLogSince = ref(0)
let branchLogTimer = null

const createNames = ref([])
const namesEditorVisible = ref(false)
const namesEditorMode = ref('create')
const namesDraft = ref('')
const createFrom = ref('')
const allBranches = ref([])
const loadingBranches = ref(false)
const currentLocalBranches = reactive({})
const deleteNames = ref([])
const oldName = ref('')
const newName = ref('')
const switchLocalName = ref('')
const switchLocalBranches = reactive({})
const switchLocalNameText = computed(() => String(switchLocalName.value || '').trim())

// 远程操作需要 SSH；本地切换需要已有 local_dir。
const candidates = computed(() => {
  if (tab.value === 'switchLocal') {
    return projects.projects.filter((p) => (p.local_dir || '').trim())
  }
  return projects.projects.filter((p) => (p.ssh_host || '').trim())
})
const emptyText = computed(() =>
  tab.value === 'switchLocal'
    ? '暂无可切换的本地工程：请先在工程卡片中拉取项目到本地'
    : '暂无可操作的工程：请先在工程卡片中填写 SSH 远程地址'
)

const checkedIds = ref(new Set())

const selectedProjects = computed(() =>
  candidates.value.filter((p) => checkedIds.value.has(p.id))
)
const checkedCount = computed(() => selectedProjects.value.length)

function toggle(p) {
  const s = new Set(checkedIds.value)
  if (s.has(p.id)) s.delete(p.id)
  else s.add(p.id)
  checkedIds.value = s
}
function checkAll() {
  checkedIds.value = new Set(candidates.value.map((p) => p.id))
}
function uncheckAll() {
  checkedIds.value = new Set()
}

function defaultSwitchBranch(p) {
  return (
    currentLocalBranches[p.id] ||
    p.source_branch ||
    switchLocalNameText.value ||
    ''
  ).trim()
}

function ensureSwitchLocalBranches() {
  selectedProjects.value.forEach((p) => {
    if (!switchLocalBranches[p.id]) switchLocalBranches[p.id] = defaultSwitchBranch(p)
  })
  const validIds = new Set(selectedProjects.value.map((p) => String(p.id)))
  Object.keys(switchLocalBranches).forEach((id) => {
    if (!validIds.has(String(id))) delete switchLocalBranches[id]
  })
}

function applySwitchLocalNameToAll() {
  const branch = switchLocalNameText.value
  if (!branch) return
  selectedProjects.value.forEach((p) => {
    switchLocalBranches[p.id] = branch
  })
}

function projectBranchOptions(p) {
  const set = new Set([...(p.branches || []), ...allBranches.value])
  const current = switchLocalBranches[p.id] || p.source_branch
  if (current) set.add(current)
  return [...set].filter(Boolean).sort((a, b) => a.localeCompare(b))
}

function appendBranchLogs(entries) {
  entries.forEach(([id, text]) => {
    if (!text.includes('执行命令:')) return
    let cls = 'info'
    if (text.includes('[ERROR]')) cls = 'error'
    else if (text.includes('[WARNING]')) cls = 'warn'
    branchLogs.value.push({ id, text, cls })
  })
}

async function startBranchLogPolling() {
  await stopBranchLogPolling()
  branchLogs.value = []
  await merge.startCommandLogSession()
  try {
    const r = await api.logs(0)
    branchLogSince.value = r.since || 0
  } catch {
    branchLogSince.value = 0
  }
  branchLogTimer = setInterval(fetchBranchLogs, 300)
}

async function fetchBranchLogs() {
  try {
    const r = await api.logs(branchLogSince.value)
    if (r.logs && r.logs.length) appendBranchLogs(r.logs)
    branchLogSince.value = r.since || branchLogSince.value
  } catch {
    /* 实时日志只是辅助展示，失败不打断主流程 */
  }
}

async function stopBranchLogPolling(flush = true) {
  clearInterval(branchLogTimer)
  branchLogTimer = null
  if (flush) await fetchBranchLogs()
  await merge.stopCommandLogSession()
}

async function fetchBranchUndo() {
  try {
    branchUndo.value = await api.branchUndo()
  } catch {
    branchUndo.value = { has_undo: false }
  }
}

function normalizeBranchNames(text) {
  const seen = new Set()
  const names = []
  String(text || '')
    .split(/[\n\r,，\s]+/)
    .map((n) => n.trim())
    .filter(Boolean)
    .forEach((n) => {
      if (seen.has(n)) return
      seen.add(n)
      names.push(n)
    })
  return names
}

function openNamesEditor(mode) {
  namesEditorMode.value = mode
  if (mode === 'delete') namesDraft.value = deleteNames.value.join('\n')
  else if (mode === 'rename') namesDraft.value = newName.value
  else namesDraft.value = createNames.value.join('\n')
  namesEditorVisible.value = true
}

function openCreateNamesEditor() {
  openNamesEditor('create')
}

function applyNamesDraft() {
  const names = normalizeBranchNames(namesDraft.value)
  if (namesEditorMode.value === 'delete') deleteNames.value = names
  else if (namesEditorMode.value === 'rename') newName.value = names[0] || ''
  else createNames.value = names
  namesEditorVisible.value = false
}

// 汇总所选（或全部候选）工程的全部分支为去重排序列表，供「目标分支」下拉选择
async function loadAllBranches() {
  if (loadingBranches.value) return
  const list = checkedIds.value.size
    ? selectedProjects.value
    : candidates.value
  if (!list.length) {
    allBranches.value = []
    return
  }
  loadingBranches.value = true
  try {
    await merge.startCommandLogSession()
    const tasks = list.map(async (p) => {
      try {
        const data = tab.value === 'switchLocal'
          ? await projects.loadBranchesWithCurrent({
            ssh_host: p.ssh_host,
            project_path: p.project_path,
            local_dir: p.local_dir,
            global: { ...projects.global },
          })
          : {
            branches: await projects.loadBranches({
              ssh_host: p.ssh_host,
              project_path: p.project_path,
              local_dir: p.local_dir,
              global: { ...projects.global },
            }),
            currentBranch: '',
          }
        if (tab.value === 'switchLocal' && data.currentBranch) {
          currentLocalBranches[p.id] = data.currentBranch
          switchLocalBranches[p.id] = data.currentBranch
        }
        return data.branches
      } catch {
        return []
      }
    })
    const lists = await Promise.all(tasks)
    const set = new Set()
    lists.forEach((l) => (l || []).forEach((b) => b && set.add(b)))
    allBranches.value = [...set].sort((a, b) => a.localeCompare(b))
  } finally {
    await merge.stopCommandLogSession()
    loadingBranches.value = false
  }
}

const selectPlaceholder = computed(() => {
  if (loadingBranches.value) return '加载分支中…'
  if (!allBranches.value.length) return '未加载到分支，点「刷新」重试'
  return '选择基于哪个分支创建'
})
const namesEditorTitle = computed(() =>
  namesEditorMode.value === 'delete'
    ? '批量编辑要删除的分支名'
    : namesEditorMode.value === 'rename'
      ? '编辑新分支名'
      : '批量编辑新分支名'
)
const undoActionText = computed(() => {
  const map = { create: '创建', delete: '删除', rename: '重命名' }
  return map[(branchUndo.value && branchUndo.value.action) || ''] || '操作'
})
const undoButtonText = computed(() => `撤回本次${undoActionText.value}`)

// 打开弹窗：清空上次状态 + 自动加载全部分支
watch(
  () => props.modelValue,
  (v) => {
    if (v) {
      results.value = []
      running.value = false
      undoingBranch.value = false
      stopBranchLogPolling(false)
      branchLogs.value = []
      fetchBranchUndo()
      loadAllBranches()
    }
  }
)

// 勾选工程变化时，防抖重新加载这些工程的全部分支
let branchLoadTimer = null
watch(checkedIds, () => {
  if (tab.value === 'switchLocal') ensureSwitchLocalBranches()
  if (!props.modelValue) return
  clearTimeout(branchLoadTimer)
  branchLoadTimer = setTimeout(loadAllBranches, 300)
})

watch(tab, () => {
  if (tab.value === 'switchLocal') {
    ensureSwitchLocalBranches()
    loadAllBranches()
  }
})

const runLabel = computed(() => {
  const map = {
    create: '创建分支',
    delete: '删除分支',
    rename: '重命名分支',
    switchLocal: '切换本地分支',
  }
  return map[tab.value] || '执行'
})

const okCount = computed(() => results.value.filter((r) => r.ok).length)
const failCount = computed(() => results.value.length - okCount.value)
const undoOkCount = computed(() => undoResults.value.filter((r) => r.ok).length)
const undoFailCount = computed(() => undoResults.value.length - undoOkCount.value)
const actionLabel = computed(
  () => ({ create: '创建', delete: '删除', rename: '重命名' })[lastUndo.value?.action] || ''
)

// 与 merge store 保持一致的 payload 序列化：去掉前端临时字段
function serialize(p) {
  const { id, checked, branches, branchesLoading, ...rest } = p
  return rest
}

async function run() {
  if (running.value) return
  const list = selectedProjects.value
  if (!list.length) {
    ElMessage.warning('请至少选择一个工程')
    return
  }

  const payloads = list.map(serialize)
  let call

  if (tab.value === 'create') {
    const names = createNames.value
      .map((n) => (n || '').trim())
      .filter(Boolean)
    if (!names.length) {
      ElMessage.warning('请填写要创建的分支名')
      return
    }
    const from = createFrom.value.trim()
    if (!from) {
      ElMessage.warning('请先选择目标分支（基于哪个分支创建）')
      return
    }
    call = () => api.branchCreate({
      projects: payloads,
      branch_names: names,
      from_branch: from,
      global: { ...projects.global },
    })
  } else if (tab.value === 'delete') {
    const names = deleteNames.value
      .map((n) => (n || '').trim())
      .filter(Boolean)
    if (!names.length) {
      ElMessage.warning('请填写要删除的分支名')
      return
    }
    try {
      await ElMessageBox.confirm(
        `将删除所选 ${list.length} 个工程上的 ${names.length} 个远程分支，确定继续？`,
        '删除分支确认',
        {
          type: 'warning',
          confirmButtonText: '确定删除',
          cancelButtonText: '取消',
          confirmButtonClass: 'el-button--danger',
        }
      )
    } catch {
      return // 用户取消
    }
    call = () => api.branchDelete({
      projects: payloads,
      branch_names: names,
      global: { ...projects.global },
    })
  } else if (tab.value === 'switchLocal') {
    ensureSwitchLocalBranches()
    const missing = list.find((p) => !String(switchLocalBranches[p.id] || '').trim())
    if (missing) {
      ElMessage.warning(`请为工程「${missing.name || missing.local_dir}」选择要切换的分支`)
      return
    }
    const switchPayloads = list.map((p) => ({
      ...serialize(p),
      switch_branch: String(switchLocalBranches[p.id] || '').trim(),
    }))
    call = () => api.branchSwitchLocal({
      projects: switchPayloads,
      global: { ...projects.global },
    })
  } else {
    const oldn = oldName.value.trim()
    const newn = newName.value.trim()
    if (!oldn || !newn) {
      ElMessage.warning('请填写原分支名与新分支名')
      return
    }
    call = () => api.branchRename({
      projects: payloads,
      old_name: oldn,
      new_name: newn,
      global: { ...projects.global },
    })
  }

  running.value = true
  results.value = []
  undoResults.value = []
  try {
    await startBranchLogPolling()
    const r = await call()
    results.value = r.results || []
    if (['create', 'delete', 'rename'].includes(tab.value)) fetchBranchUndo()
    const fail = failCount.value
    if (fail === 0) ElMessage.success(`全部完成：${okCount.value} 个工程成功`)
    else if (okCount.value > 0) ElMessage.warning(`部分成功：成功 ${okCount.value}，失败 ${fail}`)
    else ElMessage.error('全部失败，请检查各工程错误信息')
    // 操作成功后刷新工程分支缓存
    if (okCount.value > 0) {
      if (tab.value === 'switchLocal') {
        selectedProjects.value.forEach((p) => {
          const r = results.value.find((x) => x.ok && x.name === p.name)
          const branch = String(switchLocalBranches[p.id] || '').trim()
          if (r && branch) p.source_branch = branch
        })
        await projects.save()
      }
      selectedProjects.value.forEach((p) => projects.loadBranchesFor(p.id))
    }
  } catch (e) {
    ElMessage.error('执行失败：' + e.message)
  } finally {
    await stopBranchLogPolling()
    running.value = false
  }
}

async function undoBranchOperation() {
  if (running.value || undoingBranch.value) return
  const items = (branchUndo.value && branchUndo.value.items) || []
  if (!items.length) return
  try {
    await ElMessageBox.confirm(
      `将撤回最近一次${undoActionText.value}的 ${items.length} 个远程分支，确定继续？`,
      '撤回分支操作',
      {
        type: 'warning',
        confirmButtonText: '确认撤回',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }
  undoingBranch.value = true
  try {
    await startBranchLogPolling()
    const r = await api.branchUndoRun()
    results.value = r.results || []
    if (r.cleared) {
      branchUndo.value = { has_undo: false }
      ElMessage.success('已撤回本次分支操作')
    } else {
      await fetchBranchUndo()
      ElMessage.warning('部分撤回失败，请检查结果')
    }
    selectedProjects.value.forEach((p) => projects.loadBranchesFor(p.id))
  } catch (e) {
    ElMessage.error('撤回分支操作失败：' + e.message)
  } finally {
    await stopBranchLogPolling()
    undoingBranch.value = false
  }
}
</script>

<style scoped>
.bm-dialog :deep(.el-dialog__header) {
  margin-right: 0;
  padding: 14px 18px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--panel2);
}
.bm-dialog :deep(.el-dialog__body) {
  padding: 0;
}
.bm-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bm-ico {
  font-size: 18px;
  color: var(--accent);
}
.bm-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.bm-sub {
  margin-left: 6px;
  font-size: 12px;
  font-weight: 400;
  color: var(--muted);
}

.bm-body {
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 74vh;
}

/* 工程选择 */
.bm-sec-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.bm-sec-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.bm-sec-count {
  font-size: 12px;
  color: var(--muted);
}
.bm-sec-actions {
  margin-left: auto;
}
.bm-empty {
  padding: 14px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  font-size: 12px;
  color: var(--muted);
  text-align: center;
}
.bm-proj-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 132px;
  overflow-y: auto;
  padding: 2px;
}
.bm-proj {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  background: var(--panel);
  transition: border-color 0.15s ease, background 0.15s ease;
  max-width: 100%;
}
.bm-proj:hover {
  border-color: var(--accent);
}
.bm-proj.active {
  border-color: var(--accent);
  background: rgba(87, 197, 132, 0.08);
}
.bm-proj-name {
  font-size: 12px;
  color: var(--text);
  overflow-wrap: anywhere;
  white-space: normal;
  min-width: 0;
}
.bm-proj-host {
  font-size: 11px;
  color: var(--muted);
  overflow-wrap: anywhere;
  white-space: normal;
  min-width: 0;
}

/* 表单 */
.bm-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}
.bm-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 0;
}
.bm-field label {
  display: block;
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.bm-field-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bm-field-row > .el-button {
  flex: none;
}
.bm-field-hint {
  margin-top: 5px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--muted);
}
.bm-tip {
  font-size: 12px;
  line-height: 1.5;
  padding: 8px 10px;
  border-radius: 6px;
}
.bm-tip.danger {
  color: var(--danger);
  background: rgba(244, 93, 93, 0.08);
  border: 1px solid rgba(244, 93, 93, 0.25);
}

.bm-switch-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 240px;
  overflow-y: auto;
  padding-right: 4px;
}

.bm-empty.small {
  padding: 10px;
}

.bm-switch-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 280px);
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
}

.bm-switch-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.bm-switch-name {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  overflow-wrap: anywhere;
  white-space: normal;
}

.bm-switch-dir {
  color: var(--muted);
  font-size: 11px;
  overflow-wrap: anywhere;
  white-space: normal;
}

/* 执行区 */
.bm-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.bm-note {
  font-size: 12px;
  color: var(--muted);
}
.bm-undo-tip {
  margin-top: -4px;
  padding: 8px 10px;
  border: 1px solid rgba(227, 179, 65, 0.35);
  border-radius: 6px;
  background: rgba(227, 179, 65, 0.08);
  color: var(--yellow);
  font-size: 12px;
}
.bm-live {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg);
}
.bm-live-head {
  padding: 7px 10px;
  border-bottom: 1px solid var(--border);
  background: var(--panel2);
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}
.bm-live-list {
  max-height: 132px;
  overflow-y: auto;
  padding: 6px 10px;
}
.bm-live-line {
  color: var(--blue);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
  word-break: break-all;
}
.bm-live-line.warn {
  color: var(--yellow);
}
.bm-live-line.error {
  color: var(--danger);
}

/* 结果 */
.bm-results {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.bm-res-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  background: var(--panel2);
  border-bottom: 1px solid var(--border);
}
.bm-undo {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid rgba(230, 162, 60, 0.35);
  border-radius: 8px;
  background: rgba(230, 162, 60, 0.06);
}
.bm-undo-note {
  font-size: 12px;
  color: var(--muted);
  flex: 1;
  min-width: 220px;
}
.bm-ok {
  font-size: 12px;
  font-weight: 500;
  color: var(--accent);
}
.bm-fail {
  font-size: 12px;
  font-weight: 500;
  color: var(--danger);
}
.bm-res-list {
  max-height: 220px;
  overflow-y: auto;
}
.bm-res {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.bm-res:last-child {
  border-bottom: none;
}
.bm-res-ico {
  margin-top: 2px;
  font-size: 14px;
  flex-shrink: 0;
}
.bm-res.ok .bm-res-ico {
  color: var(--accent);
}
.bm-res.fail .bm-res-ico {
  color: var(--danger);
}
.bm-res-main {
  min-width: 0;
  flex: 1;
}
.bm-res-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.bm-res-name {
  color: var(--text);
  font-weight: 500;
  flex-shrink: 0;
  max-width: 320px;
  overflow-wrap: anywhere;
  white-space: normal;
}
.bm-res-msg {
  color: var(--muted);
  word-break: break-all;
}
.bm-res-commands {
  margin-top: 5px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.bm-res-command {
  padding: 4px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--blue);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.5;
  word-break: break-all;
}
</style>
