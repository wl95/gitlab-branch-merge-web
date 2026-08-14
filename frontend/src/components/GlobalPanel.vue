<template>
  <section class="panel">
    <div class="panel-head">
      <h2>🌐 全局分支设置</h2>
      <span class="head-count">应用到全部工程</span>
    </div>
    <div class="panel-body">
      <div class="gp-grid">
        <div class="gp-field">
          <label>全局源分支（可输入或下拉选择）</label>
          <el-select
            v-model="store.global.source_branch"
            filterable
            allow-create
            default-first-option
            placeholder="如：feature-20260630"
            :disabled="merge.busy"
          >
            <el-option v-for="b in store.globalBranches" :key="b" :label="b" :value="b" />
          </el-select>
        </div>
        <div class="gp-field">
          <label>全局目标分支（可多选 / 搜索 / 自定义）</label>
          <el-select
            v-model="store.global.target_branches"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="搜索分支并添加"
            :disabled="merge.busy"
          >
            <el-option v-for="b in store.globalBranches" :key="b" :label="b" :value="b" />
          </el-select>
        </div>
      </div>

      <div class="gp-foot">
        <el-input
          v-model="store.global.ssh_host"
          placeholder="（可选）SSH 地址 —— 点击「加载分支」时需要"
          :disabled="merge.busy"
        />
        <el-button
          :loading="branchLoading || store.globalBranchesLoading"
          :disabled="merge.busy"
          @click="loadBranches"
        >
          ⟳ 加载分支
        </el-button>
        <el-button :disabled="merge.busy" @click="store.applyGlobalSource">应用源分支</el-button>
        <el-button :disabled="merge.busy" @click="store.applyGlobalTargets">应用目标分支</el-button>
        <el-button type="primary" :disabled="merge.busy" @click="store.applyGlobalAll">
          一键应用到全部
        </el-button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { useProjectsStore } from '../stores/projects'
import { useMergeStore } from '../stores/merge'

const store = useProjectsStore()
const merge = useMergeStore()
const branchLoading = ref(false)

async function loadBranches() {
  branchLoading.value = true
  try {
    await store.loadGlobalBranches()
  } catch (e) {
    console.error(e)
  } finally {
    branchLoading.value = false
  }
}
</script>
