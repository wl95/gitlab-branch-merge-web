<template>
  <section class="panel scan-panel">
    <div class="panel-head">
      <h2>🔍 扫描本地仓库</h2>
    </div>
    <div class="panel-body">
      <div class="scan-row">
        <el-input
          v-model="store.scanFolderPath"
          placeholder="输入本机代码目录，如 /Users/me/work/projects"
          clearable
          @keyup.enter="doScan"
        />
        <el-dropdown
          trigger="click"
          :disabled="!store.scanHistory.length"
          @command="useHistory"
        >
          <el-button plain :disabled="!store.scanHistory.length">
            <el-icon><Clock /></el-icon>
            <span v-if="store.scanHistory.length">历史</span>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="f in store.scanHistory"
                :key="f"
                :command="f"
              >{{ f }}</el-dropdown-item>
              <el-dropdown-item
                divided
                :command="'__clear__'"
              >清空历史</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button type="primary" :loading="store.scanLoading" @click="doScan">
          读取
        </el-button>
      </div>
      <div class="scan-hint">
        扫描目录下所有 git 仓库（最多递归 6 层，自动跳过缓存和依赖目录），点「加入」可将工程直接添加到下方列表。SSH 地址从仓库 remote 自动提取，若仓库未配置 remote 可稍后在卡片中手动填写。
      </div>

      <div v-show="store.scanShow" class="scan-list">
        <div v-if="store.scanLoading" class="scan-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          正在读取文件夹…
        </div>

        <template v-else-if="store.scanResult">
          <div class="scan-list-fixed">
            <div v-if="store.scanResult.warnings && store.scanResult.warnings.length" class="scan-empty warn">
              <div v-for="(w, i) in store.scanResult.warnings" :key="i">⚠ {{ w }}</div>
            </div>

            <el-input
              v-if="allRepos.length"
              v-model="keyword"
              class="scan-filter"
              placeholder="按仓库名称、路径或 SSH 地址筛选"
              clearable
            />

            <div v-if="repos.length" class="scan-checkall">
              <el-checkbox
                :model-value="allAdded"
                :indeterminate="someAdded"
                @change="toggleAll"
              >
                全选
              </el-checkbox>
              <span>{{ countText }}</span>
            </div>

            <template v-if="!repos.length && !store.scanResult.warnings?.length">
              <div class="scan-empty">{{ allRepos.length ? '没有匹配的仓库' : '该目录下没有找到 git 仓库' }}</div>
            </template>
          </div>

          <div class="scan-list-body">
            <div
              v-for="repo in repos"
              :key="repo.ssh_host || repo.path"
              class="scan-item"
              @click="toggle(repo)"
            >
              <el-checkbox :model-value="added(repo)" @click.stop @change="() => toggle(repo)" />
              <div style="flex: 1; min-width: 0">
                <div class="scan-host">{{ repo.name || repo.ssh_host }}</div>
                <div class="scan-path">{{ repo.path }}</div>
              </div>
              <el-button size="small" :type="added(repo) ? 'warning' : 'primary'" plain @click.stop="toggle(repo)">
                {{ added(repo) ? '移除' : '加入' }}
              </el-button>
            </div>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Clock } from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()
const keyword = ref('')

const allRepos = computed(() => (store.scanResult ? store.scanResult.repos : []))
const repos = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return allRepos.value
  return allRepos.value.filter((repo) => {
    const text = [
      repo.name,
      repo.path,
      repo.project_path,
      repo.ssh_host,
    ].filter(Boolean).join(' ').toLowerCase()
    return text.includes(kw)
  })
})
const countText = computed(() => {
  if (!keyword.value.trim()) return `发现 ${allRepos.value.length} 个仓库`
  return `匹配 ${repos.value.length} / ${allRepos.value.length} 个仓库`
})
const allAdded = computed(() => repos.value.length > 0 && repos.value.every((r) => added(r)))
const someAdded = computed(() => repos.value.some((r) => added(r)) && !allAdded.value)

function added(repo) {
  return store.projects.some((p) => isSameProject(p, repo))
}

// 判断已加入工程与扫描结果是否同一个仓库：
//   1) ssh_host 完全相等  →  同一个
//   2) ssh_host 都为空 + 本地路径相等  →  同一个（如未配置 remote）
function isSameProject(p, repo) {
  if (p.ssh_host && repo.ssh_host) return p.ssh_host === repo.ssh_host
  if (!p.ssh_host && !repo.ssh_host) return p.local_dir && p.local_dir === repo.path
  return false
}

function toggle(repo) {
  if (added(repo)) store.removeScanned(repo)
  else store.addScanned(repo)
}

function toggleAll(val) {
  if (val) repos.value.forEach((r) => {
    if (!added(r)) store.addScanned(r)
  })
  else repos.value.forEach((r) => {
    if (added(r)) store.removeScanned(r)
  })
}

function doScan() {
  store.scanFolder()
}

// 点击历史目录：填充输入框并立即读取
function useHistory(cmd) {
  if (cmd === '__clear__') {
    store.clearScanHistory()
    return
  }
  store.scanFolderPath = cmd
  store.scanFolder()
}
</script>
