<template>
  <div class="panel profile-panel">
    <div class="panel-head">
      <h2>配置方案</h2>
      <span class="head-count">{{ projects.profiles.length }}</span>
      <span class="head-tip">保存、切换、编辑工程内容与全局分支</span>
    </div>

    <div class="panel-body">
      <div class="profile-toolbar">
        <el-input
          v-model="newName"
          :placeholder="`方案名称（留空自动用目标分支「${suggestedName}」）`"
          clearable
          size="small"
          @keyup.enter="onSave"
        />
        <el-button type="primary" size="small" :loading="saving" @click="onSave">
          新增
        </el-button>
      </div>
      <div class="profile-toolbar-hint">
        留空时自动按全局目标分支命名。
      </div>

      <div v-if="projects.profiles.length" class="profile-list">
        <div v-for="pf in projects.profiles" :key="pf.name" class="profile-item">
          <div class="profile-main">
            <div class="profile-head">
              <div class="profile-head-left">
                <span class="profile-name">{{ pf.name }}</span>
                <div class="profile-subline">
                  <span class="profile-info">{{ pf.project_count }} 个工程</span>
                  <span class="profile-sep">·</span>
                  <span class="profile-info">{{ pf.updated }}</span>
                </div>
              </div>
              <div class="profile-actions">
                <el-button size="small" :loading="loadingName === pf.name" @click="onLoad(pf.name)">
                  切换
                </el-button>
                <el-button size="small" plain @click="openEdit(pf)">修改</el-button>
                <el-button
                  size="small"
                  type="danger"
                  plain
                  :loading="deletingName === pf.name"
                  @click="onDelete(pf.name)"
                >
                  删除
                </el-button>
              </div>
            </div>

            <div class="profile-body">
              <div class="profile-metas">
                <span v-if="pf.source_branches && pf.source_branches.length" class="profile-chip profile-chip--source">
                  源 {{ pf.source_branches.join(' / ') }}
                </span>
                <span v-if="pf.target_branches && pf.target_branches.length" class="profile-chip profile-chip--target">
                  目标 {{ pf.target_branches.join(' / ') }}
                </span>
              </div>
              <div v-if="pf.project_names && pf.project_names.length" class="profile-projects">
                <span v-for="n in pf.project_names" :key="n" class="profile-project">{{ n }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="profile-empty">暂无已保存的方案，配置好工程与目标分支后点击「保存当前配置」</div>
    </div>
  </div>

  <el-dialog
    v-model="editVisible"
    title="修改方案"
    width="960px"
    append-to-body
    class="profile-edit-dialog"
  >
    <div class="profile-edit-form">
      <div class="profile-edit-top">
        <div>
          <div class="profile-edit-name">{{ editingProfile.name }}</div>
          <div class="profile-edit-meta">
            <span>{{ editProjects.length }} 个工程</span>
            <span>·</span>
            <span>{{ editingProfile.updated }}</span>
          </div>
        </div>
        <div class="profile-edit-top-actions">
          <el-button size="small" @click="addProjectRow">新增工程</el-button>
          <el-button size="small" plain @click="duplicateFirstProject">复制首项</el-button>
        </div>
      </div>

      <div class="profile-edit-grid">
        <div class="profile-edit-left">
          <div class="profile-edit-field">
            <label>方案名称</label>
            <el-input v-model="editName" placeholder="输入新的方案名称" clearable />
          </div>
          <div class="profile-edit-field">
            <label>全局源分支</label>
            <el-input v-model="editGlobal.source_branch" placeholder="例如 feature-20260630" clearable />
          </div>
          <div class="profile-edit-field">
            <label>全局目标分支</label>
            <el-select
              v-model="editGlobal.target_branches"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="添加目标分支"
            >
              <el-option v-for="b in branchHints" :key="b" :label="b" :value="b" />
            </el-select>
          </div>
          <div class="profile-edit-field">
            <label>全局 Git 地址前缀</label>
            <el-input v-model="editGlobal.ssh_origin" placeholder="ssh://git@host:port" clearable />
          </div>
        </div>

        <div class="profile-edit-right">
          <div class="profile-edit-field">
            <label>工程列表</label>
            <div class="profile-project-editor">
              <div v-if="!editProjects.length" class="profile-project-empty">
                还没有工程，点「新增工程」
              </div>
              <div v-for="(p, idx) in editProjects" :key="p._key" class="profile-project-row">
                <div class="profile-project-row-head">
                  <strong>工程 {{ idx + 1 }}</strong>
                  <el-button text type="danger" size="small" @click="removeProjectRow(idx)">删除</el-button>
                </div>
                <div class="profile-project-grid">
                  <el-input v-model="p.name" placeholder="工程名" />
                  <el-input v-model="p.ssh_host" placeholder="SSH 地址" />
                  <el-input v-model="p.project_path" placeholder="项目路径" />
                  <el-input v-model="p.source_branch" placeholder="源分支" />
                  <el-select
                    v-model="p.target_branches"
                    multiple
                    filterable
                    allow-create
                    default-first-option
                    placeholder="目标分支"
                  >
                    <el-option v-for="b in branchHints" :key="`${p._key}-${b}`" :label="b" :value="b" />
                  </el-select>
                  <el-input v-model="p.local_dir" placeholder="本地目录（可选）" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="editVisible = false">取消</el-button>
      <el-button type="primary" :loading="editSaving" @click="saveEdit">
        保存方案
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useProjectsStore } from '../stores/projects'
import { api } from '../api'

const projects = useProjectsStore()

const newName = ref('')
const saving = ref(false)
const loadingName = ref('')
const deletingName = ref('')
const editVisible = ref(false)
const editSaving = ref(false)
const editName = ref('')
const editingProfile = reactive({ name: '', project_count: 0, updated: '' })
const editGlobal = reactive({ source_branch: '', target_branches: [], ssh_origin: '' })
const editProjects = ref([])
const branchHints = computed(() => {
  const set = new Set()
  ;(projects.global?.target_branches || []).forEach((b) => set.add(b))
  projects.projects.forEach((p) => {
    ;(p.branches || []).forEach((b) => set.add(b))
    if (p.source_branch) set.add(p.source_branch)
    ;(p.target_branches || []).forEach((b) => set.add(b))
  })
  return [...set]
})

// 保存方案时的默认命名：优先取全局目标分支的第一个
const suggestedName = computed(() => {
  const t = projects.global?.target_branches || []
  return Array.isArray(t) && t.length ? t[0] : ''
})

async function onSave() {
  const name = newName.value.trim()
  if (!projects.projects.length) {
    ElMessage.error('请先添加工程再保存方案')
    return
  }
  saving.value = true
  try {
    await projects.saveProfile(name)
    newName.value = ''
  } catch (e) {
    ElMessage.error('保存方案失败：' + e.message)
  } finally {
    saving.value = false
  }
}

function openEdit(pf) {
  loadProfileDraft(pf.name)
}

function cloneProject(p, idx) {
  return {
    _key: `${Date.now()}-${idx}-${Math.random().toString(16).slice(2)}`,
    name: p.name || '',
    ssh_host: p.ssh_host || '',
    project_path: p.project_path || '',
    source_branch: p.source_branch || '',
    target_branches: Array.isArray(p.target_branches) ? [...p.target_branches] : [],
    local_dir: p.local_dir || '',
  }
}

async function loadProfileDraft(name) {
  try {
    const r = await api.profileGet(name)
    editingProfile.name = name
    editingProfile.project_count = (r.projects || []).length
    editingProfile.updated = projects.profiles.find((p) => p.name === name)?.updated || ''
    editName.value = name
    editGlobal.source_branch = r.global?.source_branch || ''
    editGlobal.target_branches = Array.isArray(r.global?.target_branches) ? [...r.global.target_branches] : []
    editGlobal.ssh_origin = r.global?.ssh_origin || ''
    editProjects.value = (r.projects || []).map((p, idx) => cloneProject(p, idx))
    editVisible.value = true
  } catch (e) {
    ElMessage.error('打开方案失败：' + e.message)
  }
}

function addProjectRow() {
  editProjects.value.push(cloneProject({}, editProjects.value.length))
}

function duplicateFirstProject() {
  if (!editProjects.value.length) {
    addProjectRow()
    return
  }
  editProjects.value.push(cloneProject(editProjects.value[0], editProjects.value.length))
}

function removeProjectRow(idx) {
  editProjects.value.splice(idx, 1)
}

async function saveEdit() {
  const nextName = editName.value.trim()
  if (!nextName) {
    ElMessage.error('请输入方案名称')
    return
  }
  editSaving.value = true
  try {
    const projectsPayload = editProjects.value.map((p) => ({
      name: (p.name || '').trim(),
      ssh_host: (p.ssh_host || '').trim(),
      project_path: (p.project_path || '').trim(),
      source_branch: (p.source_branch || '').trim(),
      target_branches: Array.isArray(p.target_branches)
        ? p.target_branches.map((b) => (b || '').trim()).filter(Boolean)
        : [],
      local_dir: (p.local_dir || '').trim(),
    })).filter((p) => p.name || p.ssh_host || p.project_path || p.local_dir)
    await projects.saveProfilePayload(nextName, projectsPayload, {
      source_branch: (editGlobal.source_branch || '').trim(),
      target_branches: Array.isArray(editGlobal.target_branches)
        ? editGlobal.target_branches.map((b) => (b || '').trim()).filter(Boolean)
        : [],
      ssh_origin: (editGlobal.ssh_origin || '').trim(),
    })
    if (nextName !== editingProfile.name) {
      try {
        await projects.deleteProfile(editingProfile.name)
      } catch {
        /* ignore */
      }
    }
    await projects.loadProfiles()
    editVisible.value = false
  } catch (e) {
    ElMessage.error('修改方案失败：' + e.message)
  } finally {
    editSaving.value = false
  }
}

async function onLoad(name) {
  loadingName.value = name
  try {
    await projects.loadProfile(name)
  } catch (e) {
    ElMessage.error('切换方案失败：' + e.message)
  } finally {
    loadingName.value = ''
  }
}

async function onDelete(name) {
  try {
    await ElMessageBox.confirm(`确定删除方案「${name}」？`, '删除方案', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  deletingName.value = name
  try {
    await projects.deleteProfile(name)
  } catch (e) {
    ElMessage.error('删除方案失败：' + e.message)
  } finally {
    deletingName.value = ''
  }
}

onMounted(() => {
  projects.loadProfiles()
})
</script>
