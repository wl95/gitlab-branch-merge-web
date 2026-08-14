<template>
  <div class="app" :style="appStyle">
    <AppHeader />
    <main class="app-main">
      <div class="workspace">
        <aside class="workspace-sidebar">
          <ScanPanel />
          <ProfilePanel />
          <GlobalPanel />
        </aside>

        <section class="workspace-content">
          <div class="section-title">
            <div>
              工程配置
              <span class="section-sub">逐个确认 SSH、源分支和目标分支</span>
            </div>
            <span class="count">{{ projects.count }} 个工程</span>
          </div>

          <div v-if="!projects.count" class="empty-cards">
            暂无工程<br />
            点击右上角「＋ 添加工程」手动添加，或在左侧「扫描本地仓库」批量导入
          </div>

          <div class="cards">
            <ProjectCard
              v-for="p in projects.projects"
              :key="p.id"
              :project="p"
            />
          </div>
        </section>
      </div>
    </main>

    <MergePanel />
    <PickDrawer />
    <CommitsViewDialog />
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useProjectsStore } from './stores/projects'
import { useMergeStore } from './stores/merge'
import AppHeader from './components/AppHeader.vue'
import ScanPanel from './components/ScanPanel.vue'
import ProfilePanel from './components/ProfilePanel.vue'
import GlobalPanel from './components/GlobalPanel.vue'
import ProjectCard from './components/ProjectCard.vue'
import MergePanel from './components/MergePanel.vue'
import PickDrawer from './components/PickDrawer.vue'
import CommitsViewDialog from './components/CommitsViewDialog.vue'

const projects = useProjectsStore()
const merge = useMergeStore()

// 主区域右侧 padding 跟随右侧执行面板宽度联动：
//   展开时给 340px 面板 + 间距；折叠时只需 48px 图标按钮 + 间距
const appStyle = computed(() => ({
  paddingRight: merge.collapsed ? '72px' : '364px',
}))

onMounted(async () => {
  merge.restoreCollapsed()
  try {
    const st = await projects.loadState()
    if (st.busy) merge.startPolling()
    // 进入页面自动加载全部分支
    projects.autoLoadBranches()
  } catch (e) {
    ElMessage.error('加载配置失败：' + e.message)
  }
})
</script>
