<template>
  <el-drawer
    v-model="store.visible"
    size="640px"
    :with-header="false"
    custom-class="pick-drawer"
  >
    <div class="pk">
      <!-- 头部 -->
      <div class="pk-head">
        <div class="pk-title">
          <el-icon><Magnet /></el-icon>
          Cherry-Pick Commit
          <span class="pk-badge">分页加载</span>
          <el-button class="pk-close" text circle title="关闭" @click="store.close()">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
        <div class="pk-sub">{{ store.ctx ? (store.ctx.name || store.ctx.ssh_host) : '' }}</div>
        <div class="pk-branch-row">
          <span>源分支</span>
          <el-select
            v-model="store.sourceBranch"
            size="small"
            filterable
            placeholder="选择源分支"
            @change="onSourceChange"
          >
            <el-option v-for="b in branches" :key="b" :label="b" :value="b" />
          </el-select>
        </div>
      </div>

      <!-- 搜索 -->
      <div class="pk-search">
        <el-input
          v-model="store.searchKw"
          size="small"
          clearable
          placeholder="搜索已加载的 commit（消息 / SHA / 作者）"
          :prefix-icon="Search"
        />
        <span class="pk-count">
          共 {{ store.total }} 条 · 已加载 {{ store.commits.length }} 条 · 已选 {{ store.selectedCount }}
        </span>
      </div>

      <!-- 源 commit 列表（无限滚动分页） -->
      <div ref="listEl" class="pk-list" @scroll="onListScroll">
        <div v-if="store.loading" class="pk-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          正在加载 commit…
        </div>

        <template v-else>
          <div
            v-for="c in store.filteredCommits"
            :key="c.sha"
            class="pk-item"
            :class="{ checked: store.isSelected(c.sha) }"
            @click="store.toggle(c.sha)"
          >
            <el-checkbox
              :model-value="store.isSelected(c.sha)"
              @click.stop.prevent="store.toggle(c.sha)"
            />
            <div class="pk-info">
              <div class="pk-msg">{{ c.subject }}</div>
              <div class="pk-meta-row">
                <span class="pk-sha">{{ c.short }}</span>
                <span class="pk-author">{{ c.author }}</span>
                <span>{{ c.date }}</span>
              </div>
            </div>
          </div>

          <div v-if="!store.filteredCommits.length" class="pk-empty">
            {{ store.commits.length ? '没有匹配的 commit' : '暂无 commit，请确认源分支是否正确' }}
          </div>

          <div v-if="store.loadingMore" class="pk-more-loading">
            <el-icon class="is-loading"><Loading /></el-icon>
            加载更多…
          </div>
          <div v-else-if="!store.hasMore && store.commits.length" class="pk-more-end">
            已加载全部 {{ store.total }} 条 commit
          </div>
        </template>
      </div>

      <!-- 目标分支参考（只读） -->
      <div class="pk-target">
        <div class="pk-target-head">
          <span>目标分支参考（只读）</span>
          <el-select
            v-model="store.viewTargetBranch"
            size="small"
            placeholder="选择参考分支"
            @change="onViewTargetChange"
          >
            <el-option v-for="t in store.targets" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <div class="pk-target-list">
          <div v-if="store.targetLoading" class="pk-loading">
            <el-icon class="is-loading"><Loading /></el-icon>
            加载中…
          </div>
          <template v-else>
            <div v-for="c in store.targetCommits" :key="c.sha" class="pk-item-readonly">
              <span class="pk-readonly-badge">只读</span>
              <div class="pk-info">
                <div class="pk-msg">{{ c.subject }}</div>
                <div class="pk-meta-row">
                  <span class="pk-sha">{{ c.short }}</span>
                  <span class="pk-author">{{ c.author }}</span>
                  <span>{{ c.date }}</span>
                </div>
              </div>
            </div>
            <div v-if="!store.targetCommits.length" class="pk-empty">
              该分支暂无 commit 记录
            </div>
          </template>
        </div>
      </div>

      <!-- 底部操作 -->
      <div class="pk-foot">
        <div class="pk-pick-target">
          <span>Pick 到</span>
          <el-select v-model="store.pickTarget" placeholder="选择目标分支">
            <el-option v-for="t in store.targets" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <el-button
          class="pk-pick-btn"
          type="primary"
          :loading="store.picking"
          :disabled="!store.selectedCount || !store.pickTarget"
          @click="store.doPick()"
        >
          Pick{{ store.selectedCount ? ` ${store.selectedCount} 个` : '' }} commit
        </el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Close, Loading, Magnet, Search } from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'
import { usePickStore } from '../stores/pick'

const store = usePickStore()
const projects = useProjectsStore()
const listEl = ref(null)

// 源工程的分支缓存（实时从 projects store 获取）
const branches = computed(() => {
  if (!store.ctx) return []
  const p = projects.projects.find((x) => x.id === store.ctx.id)
  return p ? p.branches : []
})

function onSourceChange() {
  store.selected = []
  store.searchKw = ''
  store.loadCommits(true)
}

function onViewTargetChange(val) {
  store.loadTargetCommits(val)
}

// 触底加载下一页
function onListScroll(e) {
  const el = e.target
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 60) {
    store.loadMore()
  }
}
</script>
