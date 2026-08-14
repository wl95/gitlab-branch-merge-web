<template>
  <div class="card" :class="{ selected: project.checked }">
    <div class="card-head">
      <el-checkbox v-model="project.checked">参与合并</el-checkbox>
      <div class="project-name" :title="project.name">{{ project.name || '（未命名工程）' }}</div>
      <div class="head-tools">
        <el-button
          size="small"
          circle
          :loading="branchLoading || project.branchesLoading"
          :disabled="merge.busy"
          title="加载 / 刷新分支列表"
          @click="loadBranches"
        >
          <el-icon><Refresh /></el-icon>
        </el-button>
        <el-button
          size="small"
          circle
          type="danger"
          plain
          title="删除工程"
          @click="removeProject"
        >
          <el-icon><Close /></el-icon>
        </el-button>
      </div>
    </div>

    <div class="card-field">
      <label>SSH 地址 *</label>
      <el-input
        ref="hostInput"
        v-model="project.ssh_host"
        :disabled="merge.busy"
        placeholder="ssh://git@host:port/group/project.git"
      />
    </div>

    <div class="card-field">
      <label>项目路径（可选）</label>
      <el-input
        v-model="project.project_path"
        :disabled="merge.busy"
        placeholder="group/project"
      />
    </div>

    <div class="card-field">
      <label>分支1 · 源分支 *</label>
      <el-select
        v-model="project.source_branch"
        filterable
        allow-create
        default-first-option
        placeholder="输入或点击选择分支"
        :disabled="merge.busy"
      >
        <el-option v-for="b in project.branches" :key="b" :label="b" :value="b" />
      </el-select>
    </div>

    <div class="card-field">
      <label>目标分支（可多选，支持搜索 / 自定义）*</label>
      <el-select
        v-model="project.target_branches"
        multiple
        filterable
        allow-create
        default-first-option
        placeholder="输入关键词搜索分支并添加"
        :disabled="merge.busy"
      >
        <el-option v-for="b in project.branches" :key="b" :label="b" :value="b" />
      </el-select>
    </div>

    <div class="card-field pick-btn-row">
      <el-button
        class="action-btn action-btn--info"
        :disabled="merge.busy || !canViewCommits"
        :loading="commitsLoading"
        :title="canViewCommits ? '查看本次合并的 commit 列表及每个 commit 的代码改动' : '请先选择源/目标分支'"
        @click="openCommitsView"
      >
        <el-icon><ChatLineRound /></el-icon>
        <span>{{ commitsLoading ? '加载 commit…' : '查看待合并 commit' }}</span>
      </el-button>
      <el-button
        class="action-btn action-btn--pick"
        :disabled="merge.busy"
        :loading="pickLoading"
        @click="openPick"
      >
        <el-icon><Magnet /></el-icon>
        <span>{{ pickLoading ? '打开中…' : '多选 Commit 并 Pick' }}</span>
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatLineRound, Close, Magnet, Refresh } from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'
import { useMergeStore } from '../stores/merge'
import { usePickStore } from '../stores/pick'
import { useCommitsViewStore } from '../stores/commitsView'
import { api } from '../api'

const props = defineProps({
  project: { type: Object, required: true },
})

const store = useProjectsStore()
const merge = useMergeStore()
const pick = usePickStore()
const view = useCommitsViewStore()

// 是否允许查看待合并 commit（至少要有源/目标分支 + 仓库路径）
const canViewCommits = computed(() => {
  const p = props.project
  return !!(p.local_dir && p.source_branch && p.target_branches && p.target_branches.length)
})
const branchLoading = ref(false)
const commitsLoading = ref(false)
const pickLoading = ref(false)
const hostInput = ref(null)

// 新增的卡片自动聚焦 SSH 输入框
watch(
  () => store.lastAddedId,
  (id) => {
    if (id === props.project.id && !props.project.ssh_host) {
      nextTick(() => hostInput.value && hostInput.value.focus())
    }
  },
  { immediate: true }
)

// SSH 地址 / 项目路径变化时，自动重新加载分支（防抖 500ms）
// 包含：手动填写 ssh_host、修改 project_path
let reloadTimer = null
watch(
  () => [props.project.ssh_host, props.project.project_path],
  ([ssh, pp], [oldSsh, oldPp]) => {
    if (reloadTimer) clearTimeout(reloadTimer)
    if (!ssh || !ssh.trim()) return
    reloadTimer = setTimeout(() => {
      store.loadBranchesFor(props.project.id)
    }, 500)
  }
)

async function loadBranches() {
  const p = props.project
  if (!p.ssh_host.trim()) {
    ElMessage.error('请先填写 SSH 地址')
    return
  }
  branchLoading.value = true
  try {
    const branches = await store.loadBranches({
      ssh_host: p.ssh_host,
      project_path: p.project_path,
    })
    store.setBranches(p.id, branches)
    if (!branches.length) ElMessage.warning('未发现可用的分支')
    else ElMessage.success(`已加载 ${branches.length} 个分支`)
  } catch (e) {
    ElMessage.error('加载分支失败：' + e.message)
  } finally {
    branchLoading.value = false
  }
}

// 打开「查看待合并 commit」弹窗：loading 由卡片本地状态控制，按钮立即进入 loading，
// 直到弹窗内部完成 _loadRange 后再结束；防止双击导致弹窗被重入打开。
async function openCommitsView() {
  if (commitsLoading.value || view.visible) return
  commitsLoading.value = true
  try {
    await view.open(props.project)
  } finally {
    commitsLoading.value = false
  }
}

// 打开「多选 Commit 并 Pick」弹窗：pick.open 为同步动作，这里包一层让按钮也能
// 走 loading 体验（视觉反馈），避免一眼点过没反应。
async function openPick() {
  if (pickLoading.value || pick.visible) return
  pickLoading.value = true
  try {
    pick.open(props.project.id)
  } finally {
    // 下一个 tick 释放，让 pick.open 内部的异步 loading 接管 UI 反馈
    setTimeout(() => { pickLoading.value = false }, 200)
  }
}

function removeProject() {
  const p = props.project
  ElMessageBox.confirm(
    `确定删除工程「${p.name || p.ssh_host || '未命名'}」吗？`,
    '删除工程',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
    .then(async () => {
      const removed = store.removeProject(p.id)
      if (removed) {
        await api.auditLog({
          action: 'project_delete',
          title: '删除工程',
          detail: `删除工程「${removed.name || removed.ssh_host || '未命名'}」`,
          undo_type: 'project_delete',
          payload: { projects: [removed] },
        })
      }
    })
    .catch(() => {})
}
</script>
