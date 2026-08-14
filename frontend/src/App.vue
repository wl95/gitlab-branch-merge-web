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
import { ElMessage, ElMessageBox } from 'element-plus'
import { useProjectsStore } from './stores/projects'
import { useMergeStore } from './stores/merge'
import { api } from './api'
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

const selectedProjectCount = computed(() => projects.projects.filter((p) => p.checked).length)
const allProjectsChecked = computed(() => projects.count > 0 && selectedProjectCount.value === projects.count)
const someProjectsChecked = computed(() => selectedProjectCount.value > 0 && selectedProjectCount.value < projects.count)

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
