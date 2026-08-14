<template>
  <div class="panel profile-panel">
    <div class="panel-head">
      <h2>配置方案</h2>
      <span class="head-count">{{ projects.profiles.length }}</span>
      <span class="head-tip">按目标分支保存多套配置，随时切换</span>
    </div>

    <div class="panel-body">
      <!-- 保存当前配置 -->
      <div class="save-row">
        <el-input
          v-model="newName"
          :placeholder="`方案名称（留空自动用目标分支「${suggestedName}」）`"
          clearable
          size="small"
          @keyup.enter="onSave"
        />
        <el-button type="primary" size="small" :loading="saving" @click="onSave">
          保存当前配置
        </el-button>
      </div>

      <!-- 已保存方案列表 -->
      <div v-if="projects.profiles.length" class="profile-list">
        <div v-for="pf in projects.profiles" :key="pf.name" class="profile-item">
          <div class="profile-main">
            <span class="profile-name">{{ pf.name }}</span>
            <span class="profile-meta">
              <template v-if="pf.source_branches && pf.source_branches.length">
                <span class="profile-label">源分支</span>
                <el-tag
                  v-for="s in pf.source_branches"
                  :key="'s' + s"
                  size="small"
                  type="success"
                  effect="plain"
                >{{ s }}</el-tag>
              </template>
              <template v-if="pf.target_branches && pf.target_branches.length">
                <span class="profile-label">目标</span>
                <el-tag
                  v-for="t in pf.target_branches"
                  :key="'t' + t"
                  size="small"
                  type="info"
                  effect="plain"
                >{{ t }}</el-tag>
              </template>
              <span class="profile-info">{{ pf.project_count }} 工程 · {{ pf.updated }}</span>
            </span>
            <div v-if="pf.project_names && pf.project_names.length" class="profile-projects">
              <span
                v-for="n in pf.project_names"
                :key="n"
                class="profile-project"
              >{{ n }}</span>
            </div>
          </div>
          <div class="profile-actions">
            <el-button size="small" :loading="loadingName === pf.name" @click="onLoad(pf.name)">
              切换
            </el-button>
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
      </div>
      <div v-else class="profile-empty">暂无已保存的方案，配置好工程与目标分支后点击「保存当前配置」</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useProjectsStore } from '../stores/projects'

const projects = useProjectsStore()

const newName = ref('')
const saving = ref(false)
const loadingName = ref('')
const deletingName = ref('')

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
