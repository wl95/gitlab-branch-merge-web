<template>
  <el-dialog
    v-model="store.visible"
    width="920"
    top="5vh"
    :close-on-click-modal="false"
    class="cv-dialog"
    @closed="store.close()"
    @close="store.close()"
  >
    <template #header>
      <div class="cv-header">
        <el-icon class="cv-ico"><DataLine /></el-icon>
        <div class="cv-title">
          待合并的 commit
          <span class="cv-sub">
            {{ store.ctx ? (store.ctx.name || store.ctx.ssh_host || '未命名工程') : '' }}
          </span>
        </div>
      </div>
    </template>

    <div v-if="store.ctx" class="cv-body">
      <!-- 路径 + 目标分支下拉 -->
      <div class="cv-flow">
        <span class="cv-label">源分支</span>
        <span class="cv-branch src">{{ store.ctx.source_branch || '（未设置）' }}</span>
        <span class="cv-arrow">→</span>
        <span class="cv-label">目标分支</span>
        <el-select
          v-if="store.targets.length > 1"
          v-model="store.currentTarget"
          size="small"
          style="min-width: 200px"
          @change="store.selectTarget"
        >
          <el-option v-for="t in store.targets" :key="t" :label="t" :value="t" />
        </el-select>
        <span v-else class="cv-branch tgt">{{ store.currentTarget || '（未设置）' }}</span>

        <span class="cv-count">
          共 {{ store.total || store.items.length }} 个 commit 即将合并
          <template v-if="store.truncated">（仅展示前 {{ store.items.length }} 个）</template>
        </span>
        <span v-if="hasMergeOnly" class="cv-merge-tip" title="目标分支已包含源分支的所有内容变更，下列合并提交因内容已并入但本身仍作为合并动作保留显示">
          含合并提交
        </span>
        <el-button text type="primary" size="small" :loading="store.loading" @click="store.selectTarget(store.currentTarget)">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>

      <!-- 列表 -->
      <div class="cv-list" v-loading="store.loading">
        <div v-if="!store.loading && !store.items.length" class="cv-empty">
          {{ store.currentTarget ? '该目标分支暂无即将合并的新 commit（已是最新）' : '请先选择目标分支' }}
        </div>

        <div v-for="c in store.items" :key="c.sha" class="cv-item">
          <div class="cv-row" @click="store.toggleDiff(c.sha)">
            <div class="cv-avatar">{{ c.author.slice(0, 1).toUpperCase() }}</div>
            <div class="cv-main">
              <div class="cv-msg">
                <el-tag v-if="isMerge(c)" type="warning" size="small" effect="dark" class="cv-merge-tag">
                  Merge
                </el-tag>
                {{ c.subject }}
              </div>
              <div class="cv-meta">
                <span class="cv-sha">{{ c.short }}</span>
                <span class="cv-author">{{ c.author }}</span>
                <span class="cv-date">{{ c.date }}</span>
                <span v-if="diffSummary(c.sha)" class="cv-files">
                  {{ diffSummary(c.sha) }}
                </span>
              </div>
            </div>
            <el-button
              text
              size="small"
              :type="store.openDiff[c.sha] ? 'danger' : 'primary'"
              @click.stop="store.toggleDiff(c.sha)"
            >
              <el-icon>
                <component :is="store.openDiff[c.sha] ? ArrowUp : ArrowDown" />
              </el-icon>
              {{ store.openDiff[c.sha] ? '收起' : '查看改动' }}
            </el-button>
          </div>

          <div v-show="store.openDiff[c.sha]" class="cv-diff">
            <div v-if="diffState(c.sha) === 'loading'" class="cv-diff-loading">
              <el-icon class="is-loading"><Loading /></el-icon>
              加载 diff…
            </div>
            <div v-else-if="diffState(c.sha) === 'error'" class="cv-diff-error">
              {{ diffData(c.sha).error || '读取 diff 失败' }}
            </div>
            <template v-else-if="diffData(c.sha)">
              <div class="cv-diff-header">
                <span class="cv-diff-sha">{{ diffData(c.sha).short }}</span>
                <span class="cv-diff-meta">
                  {{ diffData(c.sha).files_count }} 个文件
                  <span class="cv-add">+{{ totalAdditions(c.sha) }}</span>
                  <span class="cv-del">-{{ totalDeletions(c.sha) }}</span>
                </span>
              </div>
              <div v-if="diffData(c.sha).files && diffData(c.sha).files.length" class="cv-files-row">
                <span v-for="f in diffData(c.sha).files" :key="f.path" class="cv-file-chip">
                  {{ f.path }}
                  <span class="cv-file-stat">+{{ f.additions }} / -{{ f.deletions }}</span>
                </span>
              </div>
              <pre class="cv-patch">{{ diffData(c.sha).patch }}</pre>
              <div v-if="diffData(c.sha).truncated" class="cv-truncated">
                （diff 内容过长已截断，仅展示前 2000 行）
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="store.close()">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowDown, ArrowUp, DataLine, Loading, Refresh } from '@element-plus/icons-vue'
import { useCommitsViewStore } from '../stores/commitsView'

const store = useCommitsViewStore()

function diffState(sha) {
  const c = store.diffCache[sha]
  return c ? c.state : 'loading'
}

// 判断是否为合并提交：subject 以 "Merge" 开头，或后端标记为 merge_only
function isMerge(c) {
  if (!c || !c.subject) return false
  return c.merge_only || /^Merge(\s|[:\-]|$)/i.test(c.subject)
}
const hasMergeOnly = computed(() => store.items.some((c) => c && c.merge_only))
function diffData(sha) {
  const c = store.diffCache[sha]
  if (!c) return null
  return c.data || null
}
function diffSummary(sha) {
  const c = store.diffCache[sha]
  if (c && c.state === 'ok' && c.data && Array.isArray(c.data.files) && c.data.files.length) {
    return `${c.data.files_count} 文件`
  }
  return ''
}
function totalAdditions(sha) {
  const c = store.diffCache[sha]
  if (!c || c.state !== 'ok') return 0
  return (c.data.files || []).reduce((a, f) => a + (f.additions || 0), 0)
}
function totalDeletions(sha) {
  const c = store.diffCache[sha]
  if (!c || c.state !== 'ok') return 0
  return (c.data.files || []).reduce((a, f) => a + (f.deletions || 0), 0)
}
</script>
