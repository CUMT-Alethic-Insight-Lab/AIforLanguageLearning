<script setup lang="ts">
/**
 * @fileoverview 应用根组件 (Root Component)
 * @description 这是 Vue 应用的顶层组件，定义了应用的基本布局结构。
 *              
 *              布局结构：
 *              - 侧边栏 (Sidebar): 包含导航菜单，固定在左侧。
 *              - 主内容区 (Main Content): 右侧区域，用于显示路由匹配的页面组件。
 *              
 *              功能特性：
 *              - 响应式布局 (Flexbox)。
 *              - 路由视图 (Router View) 的过渡动画 (Fade)。
 *              - 全局样式定义 (如过渡效果)。
 *              - 实时助教系统事件监听与悬浮窗集成。
 */
import { onMounted, onUnmounted } from 'vue';
import { useRoute } from 'vue-router';
import Sidebar from './components/Sidebar.vue';
import { useAssistantStore } from './stores/assistant';

const assistant = useAssistantStore();
const route = useRoute();

onMounted(() => {
  // 初始化实时助教：注册系统事件监听（截图、划词）、建立 RTA WebSocket
  if (localStorage.getItem('auth_token')) {
    assistant.init();
  }
});

onUnmounted(() => {
  assistant.cleanup();
});
</script>

<template>
  <!-- 应用主容器：全屏高度，深色背景，白色文字 -->
  <div class="flex h-screen bg-gray-900 text-white overflow-hidden">
    <!-- 侧边栏组件：提供全局导航功能 -->
    <Sidebar v-if="!route.meta.public" />

    <!-- 主内容区域：占据剩余空间，垂直排列 -->
    <main class="flex-1 flex flex-col min-w-0 overflow-hidden relative transition-all duration-300">
      <!-- 路由视图容器：处理页面切换和滚动 -->
      <div class="flex-1 overflow-auto relative">
        <!-- RouterView 用于渲染当前路由匹配的组件 -->
        <router-view v-slot="{ Component }">
          <!-- Transition 组件提供页面切换时的淡入淡出动画 -->
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </main>
  </div>
</template>

<style>
/* 页面切换过渡动画定义 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease; /* 透明度过渡时间为 0.2秒 */
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0; /* 进入前和离开后的透明度为 0 */
}
</style>
