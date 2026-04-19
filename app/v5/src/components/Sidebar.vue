<script setup lang="ts">
import { useRoute } from 'vue-router';

const route = useRoute();

const navItems = [
  { name: '词汇查询', path: '/', icon: '📚' },
  { name: '作文批改', path: '/essay', icon: '📝' },
  { name: '语音对话', path: '/voice', icon: '🎤' },
  { name: '学习分析', path: '/analysis', icon: '📊' },
  { name: '教师仪表盘', path: '/teacher', icon: '🎓' },
  { name: '设置', path: '/settings', icon: '⚙️' },
];
</script>

<template>
  <div class="w-64 h-screen bg-gray-900 border-r border-gray-800 flex flex-col">
    <div class="p-6 flex items-center">
      <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center mr-3">
        <span class="text-xl font-bold text-white">AI</span>
      </div>
      <h1 class="text-lg font-semibold text-white">语言学习</h1>
    </div>

    <nav class="flex-1 px-4 space-y-2">
      <router-link
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="flex items-center px-4 py-3 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
        :class="{ 'bg-gray-800 text-white border-l-4 border-indigo-500': route.path === item.path }"
      >
        <span class="mr-3 text-xl">{{ item.icon }}</span>
        <span>{{ item.name }}</span>
      </router-link>
    </nav>

    <div class="p-4 border-t border-gray-800">
      <div class="text-xs text-gray-500 text-center">
        v5.0.0 (Vue 3 Migration)
      </div>
    </div>
  </div>
</template>
