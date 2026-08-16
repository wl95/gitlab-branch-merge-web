<template>
  <aside class="exec-panel" :class="{ collapsed: merge.collapsed }">
    <div class="exec-head">
      <h2>⚡ 执行合并</h2>
      <div class="grow"></div>
      <div class="exec-status">
        <span class="status-dot" :class="{ running: merge.busy || merge.commandStreaming }"></span>
        <span>{{ merge.busy ? '任务运行中' : merge.commandStreaming ? '命令执行中' : '空闲' }}</span>
      </div>
      <el-button text circle title="折叠 / 展开" @click="merge.toggleCollapsed">
        <el-icon :style="{ transform: merge.collapsed ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }">
          <ArrowLeft />
        </el-icon>
      </el-button>
    </div>

    <div v-show="!merge.collapsed" class="exec-body">
      <div class="merge-queue-wrap">
        <div class="merge-queue-head">
          <div>
            <span class="queue-title">待合并工程</span>
            <span class="queue-subtitle">已选择 {{ queue.length }} 个工程 · 可执行 {{ runnableCount }} 个工程</span>
          </div>
          <span class="queue-count">{{ queue.length }}</span>
        </div>
        <template v-if="queue.length">
          <div
            v-for="x in queue"
            :key="x.id"
            class="qitem"
            :class="{ warn: !x.valid || x.commitError, empty: x.noContent }"
            :title="x.noContent ? '没有合并内容，开始合并时不会参与' : ''"
          >
            <div class="qhead">
              <div class="qname">{{ x.name || x.ssh_host }}</div>
              <el-button
                v-if="x.valid && x.hasContent"
                size="small"
                text
                type="primary"
                :icon="ChatLineRound"
                @click="viewCommits(x)"
                title="查看本次将合并的 commit 及每个 commit 的代码改动"
              >
                查看 commit
              </el-button>
            </div>
            <div class="qflow">
              <span class="qsource">{{ x.source_branch || '?' }}</span>
              <span class="qarrow">→</span>
              <template v-if="x.target_branches.length">
                <span
                  v-for="t in x.target_branches"
                  :key="t"
                  class="qtarget"
                  :class="{ empty: x.targets[t] === 0, checking: x.countLoading }"
                >
                  {{ t }}
                  <small v-if="x.countLoading">检测中</small>
                  <small v-else-if="typeof x.targets[t] === 'number'">{{ x.targets[t] }} commit</small>
                </span>
              </template>
              <span v-else class="qtarget">?目标</span>
            </div>
            <div v-if="!x.valid" class="qwarn">⚠ 缺少：{{ missingText(x) }}</div>
            <div v-else-if="x.commitError" class="qwarn">⚠ commit 数量检测失败：{{ x.commitError }}</div>
            <div v-else-if="x.noContent" class="qwarn">没有合并内容，开始合并时不参与</div>
            <div v-else-if="x.hasContent && x.zeroTargets.length" class="qwarn">
              已置灰 {{ x.zeroTargets.length }} 个无合并内容的目标分支
            </div>
          </div>
        </template>
        <div v-else class="queue-empty">暂未勾选「参与合并」的工程</div>
      </div>

      <div ref="logEl" class="log">
        <template v-if="merge.logs.length">
          <div v-for="l in merge.logs" :key="l.id" class="log-line" :class="l.cls">{{ l.text }}</div>
        </template>
        <div v-else class="log-empty">尚未开始执行，日志将显示在这里</div>
      </div>

      <div v-if="merge.undo && merge.undo.has_undo" class="undo-bar">
        <div class="undo-info">
          最近合并于 {{ merge.undo.merged_at }}，共 {{ merge.undo.items.length }} 个分支可撤回
        </div>
        <el-button
          type="danger"
          plain
          size="small"
          :loading="merge.busy"
          @click="confirmUndo"
        >
          撤回合并
        </el-button>
      </div>

      <div v-if="merge.undo && merge.undo.has_undo" class="undo-commits">
        <div class="uc-title">
          <span>本次合并的 commit</span>
          <span class="uc-total">共 {{ totalCommits }} 个 · {{ merge.undo.items.length }} 个分支</span>
        </div>
        <div v-for="(it, idx) in merge.undo.items" :key="idx" class="uc-item">
          <div class="uc-head" @click="toggleItem(idx)">
            <span class="uc-name">{{ it.name }}</span>
            <span class="uc-branch">{{ it.branch }}</span>
            <span class="uc-count" :class="{ zero: !it.commit_count }">
              {{ it.commit_count ?? 0 }} 个 commit
            </span>
            <el-icon class="uc-toggle">
              <ArrowDown v-if="!openMap[idx]" />
              <ArrowUp v-else />
            </el-icon>
          </div>
          <div v-show="openMap[idx]" class="uc-body">
            <div v-if="!it.commits || !it.commits.length" class="uc-empty">
              无 commit 详情（可能为空合并，或快照在更早版本产生）
            </div>
            <div v-for="c in (it.commits || [])" :key="c.sha" class="uc-commit">
              <span class="uc-sha" :title="c.sha">{{ c.short }}</span>
              <span class="uc-subject" :title="c.subject">{{ c.subject }}</span>
              <span class="uc-meta">{{ c.author }} · {{ c.date }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="exec-foot">
        <el-button :disabled="merge.busy" @click="clearLog">清空日志</el-button>
        <el-button
          type="primary"
          :loading="merge.busy"
          :disabled="!runnableCount"
          @click="merge.runMerge()"
        >
          {{ merge.busy ? '合并进行中…' : '执行合并' }}
        </el-button>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowLeft, ArrowUp, ChatLineRound } from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'
import { useMergeStore } from '../stores/merge'
import { useCommitsViewStore } from '../stores/commitsView'

const projects = useProjectsStore()
const merge = useMergeStore()
const view = useCommitsViewStore()
const logEl = ref(null)

// 每个分支下展开状态，key = item 在 merge.undo.items 中的下标
const openMap = reactive({})

const queue = computed(() =>
  projects.checkedProjects.map((p) => ({
    id: p.id,
    name: p.name,
    ssh_host: p.ssh_host,
    source_branch: p.source_branch,
    target_branches: p.target_branches,
    valid: !!(p.ssh_host && p.source_branch && p.target_branches.length),
    countLoading: !!merge.commitCounts[p.id]?.loading,
    targets: merge.commitCounts[p.id]?.targets || {},
    commitError: merge.commitCounts[p.id]?.error || '',
    zeroTargets: (p.target_branches || []).filter((t) => merge.commitCounts[p.id]?.targets?.[t] === 0),
    hasContent: (p.target_branches || []).some((t) => (merge.commitCounts[p.id]?.targets?.[t] || 0) > 0),
    noContent: !merge.commitCounts[p.id]?.loading &&
      Object.keys(merge.commitCounts[p.id]?.targets || {}).length > 0 &&
      (p.target_branches || []).every((t) => merge.commitCounts[p.id]?.targets?.[t] === 0),
  }))
)

const runnableCount = computed(() =>
  queue.value.filter((x) => x.valid && !x.noContent && !x.countLoading).length
)

const totalCommits = computed(() => {
  const items = (merge.undo && merge.undo.items) || []
  let n = 0
  for (const it of items) n += it.commit_count || 0
  return n
})

function toggleItem(idx) {
  openMap[idx] = !openMap[idx]
}

// 当 undo items 列表变化（refetch / 撤完后清空）时，重置展开状态
watch(
  () => (merge.undo && merge.undo.items && merge.undo.items.length) || 0,
  (n, prev) => {
    if (n !== prev) {
      for (const k of Object.keys(openMap)) delete openMap[k]
    }
  }
)

watch(
  () => projects.checkedProjects.map((p) => [
    p.id,
    p.local_dir,
    p.source_branch,
    (p.target_branches || []).join(','),
  ].join('|')).join('::'),
  () => {
    projects.checkedProjects.forEach((p) => merge.refreshCommitCount(p))
  },
  { immediate: true }
)

function missingText(x) {
  const miss = []
  if (!x.ssh_host) miss.push('SSH 地址')
  if (!x.source_branch) miss.push('源分支')
  if (!x.target_branches.length) miss.push('目标分支')
  return miss.join('、')
}

async function viewCommits(x) {
  // 从 projects store 拿完整 project（queue 中只摘要了少量字段），以拿到 local_dir
  const p = projects.projects.find((pp) => pp.id === x.id)
  if (!p) {
    ElMessage.error('找不到对应工程，请重试')
    return
  }
  if (!p.local_dir) {
    ElMessage.error('工程缺少本地仓库路径，请先加载分支')
    return
  }
  await view.open(p)
}

function clearLog() {
  merge.clearLog()
}

// 撤回合并前二次确认：该操作会强制还原本地与远程分支
async function confirmUndo() {
  const items = (merge.undo && merge.undo.items) || []
  const detail = items
    .slice(0, 6)
    .map((it) => `· ${it.name}  ${it.branch}`)
    .join('\n')
  const more = items.length > 6 ? `\n… 另有 ${items.length - 6} 个分支` : ''
  try {
    await ElMessageBox.confirm(
      `将把以下分支强制还原到合并前（本地 reset --hard + 远程 force push，请谨慎）：\n\n${detail}${more}\n\n继续？`,
      '撤回合并',
      {
        confirmButtonText: '确认撤回',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      }
    )
    merge.undoMerge()
  } catch (e) {
    /* 用户取消 */
  }
}

onMounted(() => {
  merge.fetchUndo()
})

watch(
  () => merge.logs.length,
  () => {
    nextTick(() => {
      if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
    })
  }
)
</script>
