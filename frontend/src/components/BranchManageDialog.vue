<template>
  <el-dialog
    :model-value="modelValue"
    width="760"
    top="6vh"
    :close-on-click-modal="false"
    class="bm-dialog"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="bm-header">
        <el-icon class="bm-ico"><Operation /></el-icon>
        <div class="bm-title">批量分支管理</div>
        <div class="bm-sub">对多个工程同时创建 / 删除 / 重命名远程分支</div>
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
          暂无可操作的工程：请先在工程卡片中填写 SSH 远程地址
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
              <el-select
                v-model="createNames"
                multiple
                filterable
                allow-create
                default-first-option
                :reserve-keyword="false"
                :no-data-text="'输入分支名后按回车或逗号添加，可添加多个'"
                placeholder="输入分支名后按回车或逗号添加，可添加多个"
              />
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
              <el-select
                v-model="deleteNames"
                multiple
                filterable
                allow-create
                default-first-option
                :reserve-keyword="false"
                placeholder="输入分支名后按回车或逗号添加，可添加多个"
              >
                <el-option v-for="b in allBranches" :key="b" :label="b" :value="b" />
              </el-select>
              <div class="bm-field-hint">
                可输入多个分支名，将批量删除所选工程上的这些远程分支
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
              <el-input v-model="newName" placeholder="例如：feature/new-name" @keyup.enter="run" />
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
        <span class="bm-note">将依次对 {{ checkedCount }} 个工程执行，并逐工程报告结果</span>
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
            <span class="bm-res-name">{{ r.name }}</span>
            <span class="bm-res-msg">{{ r.ok ? r.message : r.error }}</span>
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
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Operation,
  Refresh,
  RefreshLeft,
  CircleCheckFilled,
  CircleCloseFilled,
} from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const projects = useProjectsStore()

const tab = ref('create')
const running = ref(false)
const results = ref([])
const lastUndo = ref(null) // { id, action } 最近一次可撤回操作
const undoResults = ref([])
const undoing = ref(false)

const createNames = ref([])
const createFrom = ref('')
const allBranches = ref([])
const loadingBranches = ref(false)
const deleteNames = ref([])
const oldName = ref('')
const newName = ref('')

// 仅对已配置 SSH 远程地址的工程可操作
const candidates = computed(() =>
  projects.projects.filter((p) => (p.ssh_host || '').trim())
)

const checkedIds = ref(new Set())
const checkedCount = computed(() => checkedIds.value.size)

const selectedProjects = computed(() =>
  projects.projects.filter((p) => checkedIds.value.has(p.id))
)

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
    const tasks = list.map(async (p) => {
      try {
        return await projects.loadBranches({
          ssh_host: p.ssh_host,
          project_path: p.project_path,
        })
      } catch {
        return []
      }
    })
    const lists = await Promise.all(tasks)
    const set = new Set()
    lists.forEach((l) => (l || []).forEach((b) => b && set.add(b)))
    allBranches.value = [...set].sort((a, b) => a.localeCompare(b))
  } finally {
    loadingBranches.value = false
  }
}

const selectPlaceholder = computed(() => {
  if (loadingBranches.value) return '加载分支中…'
  if (!allBranches.value.length) return '未加载到分支，点「刷新」重试'
  return '选择基于哪个分支创建'
})

// 打开弹窗：清空上次状态 + 自动加载全部分支
watch(
  () => props.modelValue,
  (v) => {
    if (v) {
      results.value = []
      running.value = false
      lastUndo.value = null
      undoResults.value = []
      undoing.value = false
      loadAllBranches()
    }
  }
)

// 勾选工程变化时，防抖重新加载这些工程的全部分支
let branchLoadTimer = null
watch(checkedIds, () => {
  if (!props.modelValue) return
  clearTimeout(branchLoadTimer)
  branchLoadTimer = setTimeout(loadAllBranches, 300)
})

const runLabel = computed(() => {
  const map = { create: '创建分支', delete: '删除分支', rename: '重命名分支' }
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
    call = api.branchCreate({
      projects: payloads,
      branch_names: names,
      from_branch: from,
    })
  } else if (tab.value === 'delete') {
    const dnames = deleteNames.value
      .map((n) => (n || '').trim())
      .filter(Boolean)
    if (!dnames.length) {
      ElMessage.warning('请填写要删除的分支名')
      return
    }
    const nameList = dnames.map((n) => `「${n}」`).join('、')
    try {
      await ElMessageBox.confirm(
        `将删除所选 ${list.length} 个工程上的远程分支：${nameList}，该操作不可恢复，确定继续？`,
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
    call = api.branchDelete({ projects: payloads, branch_names: dnames })
  } else {
    const oldn = oldName.value.trim()
    const newn = newName.value.trim()
    if (!oldn || !newn) {
      ElMessage.warning('请填写原分支名与新分支名')
      return
    }
    call = api.branchRename({
      projects: payloads,
      old_name: oldn,
      new_name: newn,
    })
  }

  running.value = true
  results.value = []
  undoResults.value = []
  try {
    const r = await call
    results.value = r.results || []
    lastUndo.value = r.undo_id ? { id: r.undo_id, action: r.action } : null
    const fail = failCount.value
    if (fail === 0) ElMessage.success(`全部完成：${okCount.value} 个工程成功`)
    else if (okCount.value > 0) ElMessage.warning(`部分成功：成功 ${okCount.value}，失败 ${fail}`)
    else ElMessage.error('全部失败，请检查各工程错误信息')
    // 操作成功后刷新工程分支缓存
    if (okCount.value > 0) {
      selectedProjects.value.forEach((p) => projects.loadBranchesFor(p.id))
    }
  } catch (e) {
    ElMessage.error('执行失败：' + e.message)
  } finally {
    running.value = false
  }
}

// 撤回最近一次创建/删除/重命名操作
async function undoRun() {
  if (undoing.value || !lastUndo.value) return
  const u = lastUndo.value
  try {
    await ElMessageBox.confirm(
      `撤回本次「${actionLabel.value}」操作，将自动执行逆向操作恢复分支，确定继续？`,
      '撤回确认',
      {
        type: 'warning',
        confirmButtonText: '确定撤回',
        cancelButtonText: '取消',
      }
    )
  } catch {
    return // 用户取消
  }
  undoing.value = true
  undoResults.value = []
  try {
    const r = await api.branchUndo({ undo_id: u.id })
    undoResults.value = r.results || []
    lastUndo.value = null
    const ok = undoOkCount.value
    const fail = undoFailCount.value
    if (fail === 0) ElMessage.success(`撤回完成：${ok} 项成功`)
    else if (ok > 0) ElMessage.warning(`撤回部分成功：成功 ${ok}，失败 ${fail}`)
    else ElMessage.error('撤回全部失败，请检查各工程错误信息')
    // 撤回后刷新分支缓存
    loadAllBranches()
    selectedProjects.value.forEach((p) => projects.loadBranchesFor(p.id))
  } catch (e) {
    ElMessage.error('撤回失败：' + e.message)
  } finally {
    undoing.value = false
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
  white-space: nowrap;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bm-proj-host {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
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
.bm-res-name {
  color: var(--text);
  font-weight: 500;
  flex-shrink: 0;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bm-res-msg {
  color: var(--muted);
  word-break: break-all;
}
</style>
