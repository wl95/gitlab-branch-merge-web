<template>
  <header class="app-header">
    <div class="logo">G</div>
    <div class="title-box">
      <h1>GitLab 分支合并管理台</h1>
      <div class="sub">配置工程 · 源分支合并到多个目标分支 · 批量 Cherry-Pick</div>
    </div>
    <div class="header-actions">
      <el-button type="primary" :icon="Plus" @click="addProject">添加工程</el-button>
      <el-button :icon="Operation" @click="branchManageVisible = true">
        批量分支管理
      </el-button>
      <el-button :icon="WarningFilled" @click="dangerLogVisible = true">
        危险日志
      </el-button>
      <el-button type="warning" :loading="saving" :disabled="merge.busy" @click="saveAll">
        保存全部
      </el-button>
    </div>
  </header>

  <BranchManageDialog v-model="branchManageVisible" />
  <DangerLogDialog v-model="dangerLogVisible" />
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Operation, WarningFilled } from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'
import { useMergeStore } from '../stores/merge'
import BranchManageDialog from './BranchManageDialog.vue'
import DangerLogDialog from './DangerLogDialog.vue'

const projects = useProjectsStore()
const merge = useMergeStore()
const saving = ref(false)
const branchManageVisible = ref(false)
const dangerLogVisible = ref(false)

function addProject() {
  projects.addProject()
}

async function saveAll() {
  saving.value = true
  try {
    await projects.save()
    ElMessage.success('✔ 已保存全部配置')
  } catch (e) {
    ElMessage.error('保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}
</script>
