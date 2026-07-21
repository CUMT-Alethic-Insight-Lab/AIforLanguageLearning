<script setup lang="ts">
import { useRoute } from 'vue-router';
import { BookOpen, PenLine, Mic, BarChart3, GraduationCap, Settings, LogOut } from 'lucide-vue-next';
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { AuthService } from '../services/auth';

const route = useRoute();
const router = useRouter();
const user = computed(() => AuthService.getCurrentUser());
const canViewTeacherAnalytics = computed(() => {
  const role = user.value?.role;
  return role === 'teacher' || role === 'admin';
});

const navItems = [
  { name: '词汇查询', path: '/', icon: BookOpen },
  { name: '作文批改', path: '/essay', icon: PenLine },
  { name: '语音对话', path: '/voice', icon: Mic },
  { name: '个人分析', path: '/analysis', icon: BarChart3 },
  { name: '班级学情', path: '/teacher', icon: GraduationCap, teacherOnly: true },
  { name: '智慧助教', path: '/assistant', icon: GraduationCap },
  { name: '设置', path: '/settings', icon: Settings },
];
const visibleNavItems = computed(() =>
  navItems.filter((item) => !item.teacherOnly || canViewTeacherAnalytics.value)
);

const logout = async () => {
  AuthService.logout();
  await router.replace('/login');
};
</script>

<template>
  <div class="flex h-screen w-16 shrink-0 flex-col border-r border-gray-800 bg-gray-900 md:w-64">
    <div class="flex items-center justify-center p-3 md:justify-start md:p-6">
      <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 md:mr-3">
        <span class="text-xl font-bold text-white">AI</span>
      </div>
      <h1 class="hidden text-lg font-semibold text-white md:block">语言学习</h1>
    </div>

    <nav class="flex-1 space-y-2 px-2 md:px-4">
      <router-link
        v-for="item in visibleNavItems"
        :key="item.path"
        :to="item.path"
        :aria-label="item.name"
        :title="item.name"
        class="flex items-center justify-center rounded-lg px-2 py-3 text-gray-400 transition-colors hover:bg-gray-800 hover:text-white md:justify-start md:px-4"
        :class="{ 'bg-gray-800 text-white border-l-4 border-indigo-500': route.path === item.path }"
      >
        <component :is="item.icon" class="h-5 w-5 md:mr-3" />
        <span class="hidden md:inline">{{ item.name }}</span>
      </router-link>
    </nav>

    <div class="border-t border-gray-800 p-2 md:p-4">
      <div class="mb-3 hidden text-xs text-gray-400 md:block">
        <div class="truncate text-gray-200">{{ user?.username || '未登录' }}</div>
        <div class="mt-1 uppercase tracking-wide text-gray-500">{{ user?.role || 'guest' }}</div>
      </div>
      <button
        aria-label="登出"
        title="登出"
        class="flex w-full items-center justify-center rounded-md px-2 py-2 text-sm text-gray-400 hover:bg-gray-800 hover:text-white md:justify-start md:px-3"
        @click="logout"
      >
        <LogOut class="h-4 w-4 md:mr-2" />
        <span class="hidden md:inline">登出</span>
      </button>
      <div class="mt-3 hidden text-center text-xs text-gray-500 md:block">
        HELIX v5
      </div>
    </div>
  </div>
</template>
