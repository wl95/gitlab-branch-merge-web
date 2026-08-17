import { createRouter, createWebHistory } from 'vue-router'
import ProjectMergeView from '../views/ProjectMergeView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'project-merge',
      component: ProjectMergeView,
    },
  ],
})
