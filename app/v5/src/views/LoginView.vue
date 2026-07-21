<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { AuthService } from '../services/auth';

const router = useRouter();
const username = ref('');
const password = ref('');
const error = ref('');
const isSubmitting = ref(false);

const submit = async () => {
  error.value = '';
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码';
    return;
  }
  isSubmitting.value = true;
  try {
    const ok = await AuthService.login(username.value.trim(), password.value);
    if (!ok) {
      error.value = '用户名或密码不正确';
      return;
    }
    await router.replace('/');
  } finally {
    isSubmitting.value = false;
  }
};
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-950 px-6">
    <form class="w-full max-w-sm space-y-5" @submit.prevent="submit">
      <div>
        <h1 class="text-2xl font-semibold text-white">登录 HELIX</h1>
        <p class="mt-2 text-sm text-gray-400">使用课堂账号进入学习系统。</p>
      </div>

      <label class="block">
        <span class="text-sm text-gray-300">用户名</span>
        <input
          v-model="username"
          autocomplete="username"
          class="mt-2 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-white outline-none focus:border-indigo-500"
          type="text"
        />
      </label>

      <label class="block">
        <span class="text-sm text-gray-300">密码</span>
        <input
          v-model="password"
          autocomplete="current-password"
          class="mt-2 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-white outline-none focus:border-indigo-500"
          type="password"
        />
      </label>

      <div v-if="error" class="rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-200">
        {{ error }}
      </div>

      <button
        class="w-full rounded-md bg-indigo-600 px-4 py-2 font-medium text-white disabled:opacity-60"
        :disabled="isSubmitting"
        type="submit"
      >
        {{ isSubmitting ? '登录中...' : '登录' }}
      </button>

      <p class="text-center text-sm text-gray-400">
        没有账号？
        <router-link class="text-indigo-300 hover:text-indigo-200" to="/register">注册学生账号</router-link>
      </p>
    </form>
  </div>
</template>
