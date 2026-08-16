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
                type="primary"
                plain
                size="small"
                :disabled="!selectedProjectCount || report.loading"
                :loading="report.loading"
                @click="openReportDialog"
              >
                生成提交统计
              </el-button>
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

    <el-dialog
      v-model="report.visible"
      title="指定日期提交统计"
      width="860px"
      class="commit-report-dialog"
    >
      <div class="report-toolbar">
        <el-date-picker
          v-model="report.period"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          range-separator="至"
          :clearable="false"
          @change="refreshReportAuthors"
        />
        <el-select
          v-model="report.selectedAuthors"
          multiple
          collapse-tags
          collapse-tags-tooltip
          filterable
          clearable
          placeholder="选择提交人"
          class="report-author-select"
          :disabled="!report.authors.length"
        >
          <el-option
            v-for="author in report.authors"
            :key="author"
            :label="author"
            :value="author"
          />
        </el-select>
        <el-button type="primary" :loading="report.loading" @click="generateReport">
          生成
        </el-button>
      </div>

      <div class="report-summary">
        <span>工程 {{ report.data.projects.length }} 个</span>
        <span>Commit {{ report.data.total || 0 }} 个</span>
        <span v-if="report.selectedAuthors.length">提交人 {{ report.selectedAuthors.length }} 个</span>
        <span v-if="report.error" class="report-error-text">{{ report.error }}</span>
        <el-button size="small" text :disabled="!report.data.markdown" @click="copyReport">
          复制报告
        </el-button>
        <el-button size="small" text :disabled="!report.data.markdown" @click="downloadReport">
          下载 Markdown
        </el-button>
      </div>

      <div v-if="!report.data.projects.length" class="report-empty">
        选择期间后生成统计
      </div>
      <div v-else class="report-body">
        <section
          v-for="item in report.data.projects"
          :key="item.name + item.branch"
          class="report-project"
        >
          <div class="report-project-head">
            <strong>{{ item.name }}</strong>
            <span v-if="item.branch">{{ item.branch }}</span>
            <em>{{ item.count || 0 }} commit</em>
          </div>
          <div v-if="item.error" class="report-error">{{ item.error }}</div>
          <div v-else-if="!item.commits.length" class="report-muted">无提交</div>
          <div v-else class="report-commits">
            <div v-for="c in item.commits" :key="c.sha" class="report-commit">
              <code>{{ c.short }}</code>
              <span class="report-subject">{{ c.subject }}</span>
              <span class="report-author">{{ c.author }}</span>
            </div>
          </div>
        </section>

        <el-input
          v-model="report.data.markdown"
          type="textarea"
          :rows="10"
          readonly
          class="report-markdown"
        />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
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

function todayLocal() {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// 主区域右侧 padding 跟随右侧执行面板宽度联动：
//   展开时给 340px 面板 + 间距；折叠时只需 48px 图标按钮 + 间距
const appStyle = computed(() => ({
  paddingRight: merge.collapsed ? '72px' : '364px',
}))

const selectedProjectCount = computed(() => projects.projects.filter((p) => p.checked).length)
const allProjectsChecked = computed(() => projects.count > 0 && selectedProjectCount.value === projects.count)
const someProjectsChecked = computed(() => selectedProjectCount.value > 0 && selectedProjectCount.value < projects.count)
const activeSidebarTab = ref(localStorage.getItem('gm_sidebar_tab') || 'gitlab')
const report = reactive({
  visible: false,
  loading: false,
  period: [todayLocal(), todayLocal()],
  authors: [],
  selectedAuthors: [],
  error: '',
  data: { projects: [], total: 0, markdown: '' },
})
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

function reportProjects() {
  return projects.checkedProjects.map((p) => ({ ...p }))
}

function reportTitle() {
  const [startDate, endDate] = report.period || []
  if (!startDate || !endDate) return '提交统计'
  return startDate === endDate ? `${startDate} 提交统计` : `${startDate} 至 ${endDate} 提交统计`
}

function fallbackReport(list, message) {
  const lines = [
    `# ${reportTitle()}`,
    '',
    '## 汇总',
    `- 工程数：${list.length}`,
    '- Commit 数：0',
    `- 生成状态：失败`,
    `- 失败原因：${message}`,
    '',
    '## 按工程',
    ...list.map((p) => `### ${p.name || p.project_path || p.ssh_host || '未命名工程'}\n- 统计失败：${message}`),
  ]
  return {
    projects: list.map((p) => ({
      name: p.name || p.project_path || p.ssh_host || '未命名工程',
      branch: p.source_branch || '',
      commits: [],
      authors: [],
      count: 0,
      error: message,
    })),
    total: 0,
    markdown: lines.join('\n') + '\n',
  }
}

async function openReportDialog() {
  if (!selectedProjectCount.value) {
    ElMessage.warning('请先勾选要统计的工程')
    return
  }
  report.visible = true
  await generateReport({ refreshAuthors: true })
}

async function generateReport(options = {}) {
  const list = reportProjects()
  if (!list.length) {
    ElMessage.warning('请先勾选要统计的工程')
    return
  }
  const [startDate, endDate] = report.period || []
  if (!startDate || !endDate) {
    ElMessage.warning('请选择统计期间')
    return
  }
  report.loading = true
  report.error = ''
  try {
    const r = await api.commitReport({
      projects: list,
      global: { ...projects.global },
      start_date: startDate,
      end_date: endDate,
      authors: options.refreshAuthors ? [] : report.selectedAuthors,
    })
    if (options.refreshAuthors) {
      report.authors = r.authors || []
      report.selectedAuthors = []
    } else {
      report.authors = r.authors || report.authors
    }
    report.data = {
      projects: r.projects || [],
      total: r.total || 0,
      markdown: r.markdown || '',
    }
  } catch (e) {
    const diagnostic = await api.diagnoseBackend().catch(() => '')
    const message = diagnostic || e.message
    report.error = message
    report.data = fallbackReport(list, message)
    ElMessage.error('生成提交统计失败：' + message)
  } finally {
    report.loading = false
  }
}

async function copyReport() {
  const text = report.data.markdown || ''
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('报告已复制')
  } catch {
    ElMessage.error('复制失败，请手动选中文本复制')
  }
}

function downloadReport() {
  const text = report.data.markdown || ''
  if (!text) return
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${reportTitle().replace(/\s+/g, '-')}.md`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function refreshReportAuthors() {
  if (!report.visible || !selectedProjectCount.value) return
  await generateReport({ refreshAuthors: true })
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
