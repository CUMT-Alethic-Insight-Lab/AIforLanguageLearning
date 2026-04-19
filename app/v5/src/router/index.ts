/**
 * @fileoverview 路由配置模块 (Vue Router)
 * @description 定义前端应用的路由规则，映射 URL 路径到具体的页面组件。
 *              使用 Hash 模式以确保在 Electron 环境下的兼容性。
 *              包含基于角色的导航守卫，保护教师专属页面。
 */

import { createRouter, createWebHashHistory, RouteRecordRaw } from 'vue-router'

// 引入页面组件
import HomeView from '../views/HomeView.vue'
import VoiceView from '../views/VoiceView.vue'
import AnalysisView from '../views/AnalysisView.vue'
import SettingsView from '../views/SettingsView.vue'
import EssayView from '../views/EssayView.vue'
import TeacherDashboardView from '../views/TeacherDashboardView.vue'
import StudentProfileView from '../views/StudentProfileView.vue'

/**
 * 路由表定义
 */
const routes: Array<RouteRecordRaw> = [
  {
    path: '/',
    name: 'home',
    component: HomeView,
    meta: { title: '首页' }
  },
  {
    path: '/essay',
    name: 'essay',
    component: EssayView,
    meta: { title: '作文批改' }
  },
  {
    path: '/voice',
    name: 'voice',
    component: VoiceView,
    meta: { title: '语音对话' }
  },
  {
    path: '/analysis',
    name: 'analysis',
    component: AnalysisView,
    meta: { title: '学习分析' }
  },
  {
    path: '/settings',
    name: 'settings',
    component: SettingsView,
    meta: { title: '设置' }
  },
  {
    path: '/teacher',
    name: 'teacher-dashboard',
    component: TeacherDashboardView,
    meta: { title: '教师仪表盘', requiresRole: 'teacher' }
  },
  {
    path: '/teacher/student/:student_id',
    name: 'student-profile',
    component: StudentProfileView,
    meta: { title: '学生画像', requiresRole: 'teacher' }
  }
]

/**
 * 创建路由实例
 * 
 * 使用 createWebHashHistory (Hash 模式)，URL 中会包含 '#'。
 * 这种模式不需要服务器端配置重定向，非常适合 Electron 这种本地文件系统环境。
 */
const router = createRouter({
  history: createWebHashHistory(), 
  routes
})

/**
 * 全局导航守卫 — 角色权限校验
 * 
 * 对标记了 requiresRole 的路由进行拦截，检查当前用户是否具备对应角色。
 * 未授权用户会被重定向到首页，并在控制台给出提示。
 */
router.beforeEach((to, _from, next) => {
  const requiredRole = to.meta.requiresRole as string | undefined
  if (requiredRole) {
    try {
      const raw = localStorage.getItem('auth_user')
      const user = raw ? JSON.parse(raw) : null
      const userRole = user?.role || 'student'
      if (userRole !== requiredRole) {
        console.warn(`[Router Guard] 访问被拒绝：需要角色 '${requiredRole}'，当前角色 '${userRole}'`)
        return next('/')
      }
    } catch {
      return next('/')
    }
  }
  next()
})

export default router
