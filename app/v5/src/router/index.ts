/**
 * @fileoverview 路由配置模块 (Vue Router)
 * @description 定义前端应用的路由规则，映射 URL 路径到具体的页面组件。
 *              使用 Hash 模式以确保在 Electron 环境下的兼容性。
 */

import { createRouter, createWebHashHistory, RouteRecordRaw } from 'vue-router'

// 引入页面组件
import HomeView from '../views/HomeView.vue'
import VoiceView from '../views/VoiceView.vue'
import AnalysisView from '../views/AnalysisView.vue'
import SettingsView from '../views/SettingsView.vue'
import EssayView from '../views/EssayView.vue'
import AssistantView from '../views/AssistantView.vue'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import TeacherAnalyticsView from '../views/TeacherAnalyticsView.vue'
import { AuthService, AuthUser } from '../services/auth'

/**
 * 路由表定义
 */
const routes: Array<RouteRecordRaw> = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { title: '登录', public: true }
  },
  {
    path: '/register',
    name: 'register',
    component: RegisterView,
    meta: { title: '注册', public: true }
  },
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
    path: '/teacher',
    name: 'teacher',
    component: TeacherAnalyticsView,
    meta: { title: '班级学情', allowedRoles: ['teacher', 'admin'] }
  },
  {
    path: '/assistant',
    name: 'assistant',
    component: AssistantView,
    meta: { title: '智慧助教' }
  },
  {
    path: '/settings',
    name: 'settings',
    component: SettingsView,
    meta: { title: '设置' }
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
 * 全局导航守卫 — 页面标题更新
 */
router.beforeEach((to, _from, next) => {
  const title = to.meta.title as string | undefined
  if (title) {
    document.title = `${title} - AI语言学习`
  }
  const isPublic = Boolean(to.meta.public)
  const hasToken = AuthService.hasToken()
  if (!isPublic && !hasToken) {
    next({ path: '/login' })
    return
  }
  if (isPublic && hasToken && (to.path === '/login' || to.path === '/register')) {
    next({ path: '/' })
    return
  }
  const allowedRoles = to.meta.allowedRoles as AuthUser['role'][] | undefined
  if (allowedRoles) {
    const user = AuthService.getCurrentUser()
    if (!user || !allowedRoles.includes(user.role)) {
      next({ path: '/' })
      return
    }
  }
  next()
})

export default router
