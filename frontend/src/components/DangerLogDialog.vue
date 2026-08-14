<template>
  <el-dialog
    :model-value="modelValue"
    width="760"
    top="6vh"
    class="danger-log-dialog"
    @update:model-value="$emit('update:modelValue', $event)"
    @open="load"
  >
    <template #header>
      <div class="dl-header">
        <el-icon><WarningFilled /></el-icon>
        <span>危险操作日志</span>
      </div>
    </template>

    <div class="dl-body" v-loading="loading">
      <div class="dl-toolbar">
        <el-checkbox
          :model-value="allChecked"
          :indeterminate="someChecked"
          :disabled="!logs.length"
          @change="toggleAll"
        >
          全选
        </el-checkbox>
        <el-button
          size="small"
          type="danger"
          plain
          :disabled="!checkedIds.length"
          @click="deleteChecked"
        >
          删除已选
        </el-button>
        <span>已选 {{ checkedIds.length }} / {{ logs.length }}</span>
      </div>

      <div v-if="!logs.length" class="dl-empty">暂无危险操作记录</div>
      <div v-for="item in logs" :key="item.id" class="dl-item">
        <el-checkbox
          :model-value="checkedIds.includes(item.id)"
          @change="toggleOne(item.id)"
        />
        <div class="dl-main">
          <div class="dl-title">
            <span>{{ item.title }}</span>
            <em>{{ item.time }}</em>
            <strong>{{ item.action }}</strong>
          </div>
          <div class="dl-detail">{{ item.detail || item.action }}</div>
          <div v-if="operationLines(item).length" class="dl-op-lines">
            <div v-for="line in operationLines(item)" :key="line.label" class="dl-op-line">
              <span>{{ line.label }}</span>
              <strong>{{ line.value }}</strong>
            </div>
          </div>
          <div class="dl-meta">
            <span>ID: {{ item.id }}</span>
            <span>撤回类型: {{ item.undo_type || '无' }}</span>
          </div>
          <el-collapse class="dl-collapse">
            <el-collapse-item title="查看完整内容" :name="item.id">
              <div v-if="extractCommands(item).length" class="dl-command-block">
                <div class="dl-command-title">本次执行命令</div>
                <div v-for="cmd in extractCommands(item)" :key="cmd" class="dl-command-line">
                  {{ cmd }}
                </div>
              </div>
              <pre class="dl-json">{{ formatItem(item) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>
        <el-button
          v-if="canUndo(item)"
          size="small"
          type="danger"
          plain
          @click="undo(item)"
        >
          撤回
        </el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { WarningFilled } from '@element-plus/icons-vue'
import { api } from '../api'
import { useProjectsStore } from '../stores/projects'
import { useMergeStore } from '../stores/merge'

defineProps({
  modelValue: { type: Boolean, default: false },
})
defineEmits(['update:modelValue'])

const projects = useProjectsStore()
const merge = useMergeStore()
const loading = ref(false)
const logs = ref([])
const checkedIds = ref([])
const allChecked = computed(() => logs.value.length > 0 && checkedIds.value.length === logs.value.length)
const someChecked = computed(() => checkedIds.value.length > 0 && checkedIds.value.length < logs.value.length)

async function load() {
  loading.value = true
  try {
    const r = await api.auditLogs()
    logs.value = r.logs || []
    checkedIds.value = checkedIds.value.filter((id) => logs.value.some((x) => x.id === id))
  } catch (e) {
    const suffix = e.message.includes('404') ? '，请重启 webapp.py 后再试' : ''
    ElMessage.error('读取危险操作日志失败：' + e.message + suffix)
  } finally {
    loading.value = false
  }
}

function toggleOne(id) {
  if (checkedIds.value.includes(id)) checkedIds.value = checkedIds.value.filter((x) => x !== id)
  else checkedIds.value = [...checkedIds.value, id]
}

function toggleAll(checked) {
  checkedIds.value = checked ? logs.value.map((x) => x.id) : []
}

async function deleteChecked() {
  const count = checkedIds.value.length
  if (!count) return
  try {
    await ElMessageBox.confirm(`确定删除已选的 ${count} 条危险日志吗？`, '删除危险日志', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  const r = await api.auditDelete(checkedIds.value)
  ElMessage.success(`已删除 ${r.removed || 0} 条危险日志`)
  checkedIds.value = []
  await load()
}

function formatItem(item) {
  return JSON.stringify(item, null, 2)
}

function payloadOf(item) {
  return (item && item.payload) || {}
}

function requestOf(item) {
  return payloadOf(item).request || {}
}

function namesText(names) {
  return (names || []).filter(Boolean).join('、') || '-'
}

function operationLines(item) {
  const payload = payloadOf(item)
  const request = requestOf(item)
  const results = payload.results || []
  const undoItems = payload.undo_items || []
  if (item.action === 'branch_create') {
    return [
      { label: '目标分支（基于）', value: request.from_branch || '-' },
      { label: '新分支名', value: namesText(request.branch_names || undoItems.map((x) => x.branch_name)) },
      { label: '执行工程', value: `${(request.projects || []).length || undoItems.length} 个` },
    ]
  }
  if (item.action === 'branch_delete') {
    return [
      { label: '删除分支', value: namesText(request.branch_names || undoItems.map((x) => x.branch_name)) },
      { label: '成功删除', value: `${undoItems.length} 个` },
    ]
  }
  if (item.action === 'branch_rename') {
    return [
      { label: '原分支名', value: request.old_name || namesText(undoItems.map((x) => x.old_name)) },
      { label: '新分支名', value: request.new_name || namesText(undoItems.map((x) => x.new_name)) },
      { label: '成功修改', value: `${undoItems.length || results.filter((x) => x.ok).length} 个` },
    ]
  }
  if (item.action === 'cherry_pick') {
    return [
      { label: '目标分支', value: payload.target_branch || '-' },
      { label: 'Commit', value: namesText(payload.commits) },
    ]
  }
  if (item.action === 'merge') {
    return [
      { label: '可撤回分支', value: namesText((payload.items || []).map((x) => x.branch)) },
    ]
  }
  return []
}

function extractCommands(item) {
  const commands = []
  ;(item.commands || []).forEach((cmd) => commands.push(cmd))
  const seen = new Set()
  return commands.filter((cmd) => {
    if (!cmd || seen.has(cmd)) return false
    seen.add(cmd)
    return true
  })
}

function canUndo(item) {
  return ['branch', 'merge', 'project_delete', 'profile_delete'].includes(item.undo_type)
}

async function undo(item) {
  try {
    await ElMessageBox.confirm(`确定撤回「${item.title}」吗？`, '撤回危险操作', {
      type: 'warning',
      confirmButtonText: '撤回',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  if (item.undo_type === 'branch') {
    await api.branchUndoRun()
    ElMessage.success('已启动分支操作撤回')
  } else if (item.undo_type === 'merge') {
    await merge.undoMerge()
  } else if (item.undo_type === 'project_delete') {
    projects.restoreProjects((item.payload && item.payload.projects) || [])
    ElMessage.success('已恢复删除的工程配置')
  } else if (item.undo_type === 'profile_delete') {
    await api.profileRestore(item.payload.name, item.payload.profile)
    await projects.loadProfiles()
    ElMessage.success('已恢复删除的配置方案')
  }
  await load()
}
</script>

<style scoped>
.dl-header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
  font-weight: 600;
}
.dl-body {
  max-height: 68vh;
  overflow-y: auto;
}
.dl-toolbar {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0 10px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}
.dl-toolbar .el-button {
  margin-left: 0;
}
.dl-toolbar span {
  color: var(--muted);
  font-size: 12px;
}
.dl-empty {
  padding: 28px;
  color: var(--muted);
  text-align: center;
}
.dl-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 2px;
  border-bottom: 1px solid var(--border);
}
.dl-main {
  flex: 1;
  min-width: 0;
}
.dl-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  flex-wrap: wrap;
}
.dl-title em {
  color: var(--muted);
  font-style: normal;
  font-size: 12px;
  font-weight: 400;
}
.dl-title strong {
  padding: 1px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--accent2);
  font-size: 11px;
  font-weight: 500;
}
.dl-detail {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
  word-break: break-all;
}
.dl-op-lines {
  margin-top: 8px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 6px;
}
.dl-op-line {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  font-size: 12px;
}
.dl-op-line span {
  display: block;
  color: var(--muted);
  margin-bottom: 2px;
}
.dl-op-line strong {
  color: var(--text);
  font-weight: 600;
  word-break: break-all;
}
.dl-meta {
  margin-top: 5px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--muted);
  font-size: 11px;
}
.dl-collapse {
  margin-top: 6px;
  --el-collapse-header-bg-color: transparent;
  --el-collapse-content-bg-color: transparent;
  --el-collapse-border-color: var(--border);
}
.dl-json {
  margin: 0;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
.dl-json {
  max-height: 260px;
  overflow: auto;
}
.dl-command-block {
  margin-bottom: 8px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
}
.dl-command-title {
  margin-bottom: 6px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}
.dl-command-line {
  color: var(--blue);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
  word-break: break-all;
}
</style>
