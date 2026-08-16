<template>
  <div class="app" :style="appStyle">
    <AppHeader />
    <main class="app-main">
      <div class="workspace">
        <aside class="workspace-sidebar">
          <div class="sidebar-tabs">
            <button
              v-for="tab in sidebarTabs"
              :key="tab.value"
              type="button"
              :class="['sidebar-tab', { active: activeSidebarTab === tab.value }]"
              @click="setSidebarTab(tab.value)"
            >
              <el-icon><component :is="tab.icon" /></el-icon>
              <span>{{ tab.label }}</span>
            </button>
          </div>
          <div class="sidebar-panel">
            <ScanPanel v-show="activeSidebarTab === 'scan'" />
            <GitlabProjectsPanel v-show="activeSidebarTab === 'gitlab'" />
            <ProfilePanel v-show="activeSidebarTab === 'profiles'" />
            <GlobalPanel v-show="activeSidebarTab === 'global'" />
          </div>
        </aside>

        <section class="workspace-content">
          <div class="section-title">
            <div class="section-heading">
              工程配置
              <span class="section-sub">逐个确认 SSH、源分支和目标分支</span>
            </div>
            <div class="section-actions">
              <el-checkbox
                :model-value="allProjectsChecked"
                :indeterminate="someProjectsChecked"
                :disabled="!projects.count || merge.busy"
                @change="toggleAllProjects"
              >
                全选
              </el-checkbox>
              <el-button
                type="danger"
                plain
                size="small"
                :disabled="!selectedProjectCount || merge.busy"
                @click="removeSelectedProjects"
              >
                删除已勾选
              </el-button>
              <span class="count">
                {{ selectedProjectCount ? `已选 ${selectedProjectCount} / ` : '' }}{{ projects.count }} 个工程
              </span>
            </div>
          </div>

          <div v-if="!projects.count" class="empty-cards">
            暂无工程<br />
              在左侧「本地」扫描仓库后批量导入工程配置
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
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Aim, FolderOpened, Setting, Tickets } from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'
import { useMergeStore } from '../stores/merge'
import { api } from '../api'
import AppHeader from '../components/AppHeader.vue'
import ScanPanel from '../components/ScanPanel.vue'
import GitlabProjectsPanel from '../components/GitlabProjectsPanel.vue'
import ProfilePanel from '../components/ProfilePanel.vue'
import GlobalPanel from '../components/GlobalPanel.vue'
import ProjectCard from '../components/ProjectCard.vue'
import MergePanel from '../components/MergePanel.vue'
import PickDrawer from '../components/PickDrawer.vue'
import CommitsViewDialog from '../components/CommitsViewDialog.vue'

const projects = useProjectsStore()
const merge = useMergeStore()

// 主区域右侧 padding 跟随右侧执行面板宽度联动：
//   展开时给 340px 面板 + 间距；折叠时只需 48px 图标按钮 + 间距
const appStyle = computed(() => ({
  paddingRight: merge.collapsed ? '72px' : '364px',
}))

const selectedProjectCount = computed(() => projects.projects.filter((p) => p.checked).length)
const allProjectsChecked = computed(() => projects.count > 0 && selectedProjectCount.value === projects.count)
const someProjectsChecked = computed(() => selectedProjectCount.value > 0 && selectedProjectCount.value < projects.count)
const activeSidebarTab = ref(localStorage.getItem('gm_sidebar_tab') || 'gitlab')
const sidebarTabs = [
  { value: 'scan', label: '本地', icon: FolderOpened },
  { value: 'gitlab', label: '远程', icon: Aim },
  { value: 'profiles', label: '方案', icon: Tickets },
  { value: 'global', label: '全局', icon: Setting },
]

function setSidebarTab(tab) {
  activeSidebarTab.value = tab
  localStorage.setItem('gm_sidebar_tab', activeSidebarTab.value)
}

function toggleAllProjects(checked) {
  projects.setAllChecked(checked)
}

function removeSelectedProjects() {
  const count = selectedProjectCount.value
  if (!count) return
  ElMessageBox.confirm(
    `确定删除已勾选的 ${count} 个工程吗？`,
    '批量删除工程',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
    .then(async () => {
      const removed = projects.removeCheckedProjects()
      if (removed.length) {
        await api.auditLog({
          action: 'project_delete',
          title: '批量删除工程',
          detail: `删除 ${removed.length} 个工程配置`,
          undo_type: 'project_delete',
          payload: { projects: removed },
        })
        ElMessage.success(`已删除 ${removed.length} 个工程`)
      }
    })
    .catch(() => {})
}

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
