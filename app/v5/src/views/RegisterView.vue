<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { AuthService } from '../services/auth';

const router = useRouter();
const username = ref('');
const email = ref('');
const password = ref('');
const error = ref('');
const isSubmitting = ref(false);

const submit = async () => {
  error.value = '';
  if (!username.value.trim() || !email.value.trim() || !password.value) {
    error.value = '请填写用户名、邮箱和密码';
    return;
  }
  if (password.value.length < 8 || !/[a-z]/.test(password.value) || !/[A-Z]/.test(password.value) || !/[0-9]/.test(password.value)) {
    error.value = '密码至少 8 位，并包含大小写字母和数字';
    return;
  }
  isSubmitting.value = true;
  try {
    const ok = await AuthService.register(username.value.trim(), email.value.trim(), password.value);
    if (!ok) {
      error.value = '注册失败，用户名或邮箱可能已存在';
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
        <h1 class="text-2xl font-semibold text-white">注册学生账号</h1>
        <p class="mt-2 text-sm text-gray-400">教师和管理员角色由管理员分配。</p>
      </div>

      <label class="block">
        <span class="text-sm text-gray-300">用户名</span>
        <input v-model="username" class="mt-2 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-white outline-none focus:border-indigo-500" type="text" />
      </label>

      <label class="block">
        <span class="text-sm text-gray-300">邮箱</span>
        <input v-model="email" class="mt-2 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-white outline-none focus:border-indigo-500" type="email" />
      </label>

      <label class="block">
        <span class="text-sm text-gray-300">密码</span>
        <input v-model="password" autocomplete="new-password" class="mt-2 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-white outline-none focus:border-indigo-500" type="password" />
      </label>

      <div v-if="error" class="rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-200">
        {{ error }}
      </div>

      <button class="w-full rounded-md bg-indigo-600 px-4 py-2 font-medium text-white disabled:opacity-60" :disabled="isSubmitting" type="submit">
        {{ isSubmitting ? '注册中...' : '注册并登录' }}
      </button>

      <p class="text-center text-sm text-gray-400">
        已有账号？
        <router-link class="text-indigo-300 hover:text-indigo-200" to="/login">返回登录</router-link>
      </p>
    </form>
  </div>
</template>
