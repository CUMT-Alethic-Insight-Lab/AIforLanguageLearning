<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';
import { useAssistantStore } from '../stores/assistant';

const assistant = useAssistantStore();
const testMessage = ref('');
const suggestions = ref<Array<{ priority: string; content: string; time: string }>>([]);

const toggleAssistant = () => {
  assistant.toggleEnabled();
};

const sendTestSuggestion = () => {
  const content = testMessage.value.trim() || '这是一条测试教学建议，用于验证智慧助教悬浮窗是否正常弹出。';
  assistant.showResultOverlay({
    title: '测试建议',
    content,
    priority: 'medium',
  });
  suggestions.value.unshift({
    priority: 'medium',
    content,
    time: new Date().toLocaleTimeString(),
  });
  if (suggestions.value.length > 10) suggestions.value.pop();
};

const clearHistory = () => {
  suggestions.value = [];
};

onMounted(() => {
  assistant.init?.();
});

onUnmounted(() => {
  // 不在这里 cleanup，因为 store 是全局的
});
</script>

<template>
  <div class="p-6 h-full overflow-y-auto">
    <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-white">智慧助教</h2>
        <p class="text-slate-400 text-sm mt-1">
          RTA 状态:
          <span :class="assistant.isConnected ? 'text-emerald-400' : 'text-rose-400'">
            {{ assistant.isConnected ? '已连接' : '未连接' }}
          </span>
        </p>
      </div>
      <div class="flex items-center gap-3">
        <button
          @click="toggleAssistant"
          class="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          :class="assistant.isEnabled ? 'bg-indigo-600 hover:bg-indigo-500 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'"
        >
          {{ assistant.isEnabled ? '助教已启用' : '助教已暂停' }}
        </button>
      </div>
    </div>

    <!-- 状态卡片 -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
        <div class="text-slate-400 text-sm">总开关</div>
        <div class="text-xl font-bold mt-2" :class="assistant.isEnabled ? 'text-emerald-400' : 'text-slate-500'">
          {{ assistant.isEnabled ? '运行中' : '已暂停' }}
        </div>
      </div>
      <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
        <div class="text-slate-400 text-sm">WebSocket</div>
        <div class="text-xl font-bold mt-2" :class="assistant.isConnected ? 'text-emerald-400' : 'text-rose-400'">
          {{ assistant.isConnected ? '已连接' : '未连接' }}
        </div>
      </div>
      <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
        <div class="text-slate-400 text-sm">最近建议</div>
        <div class="text-xl font-bold text-white mt-2">{{ suggestions.length }}</div>
      </div>
    </div>

    <!-- 测试区域 -->
    <div class="bg-slate-800 rounded-xl p-5 border border-slate-700 mb-6">
      <h3 class="text-lg font-semibold text-white mb-4">悬浮窗测试</h3>
      <div class="flex flex-col md:flex-row gap-3">
        <input
          v-model="testMessage"
          type="text"
          placeholder="输入测试消息（留空使用默认）"
          class="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
        >
        <button
          @click="sendTestSuggestion"
          class="bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg px-4 py-2 text-sm"
        >
          发送测试建议
        </button>
      </div>
      <p class="text-xs text-slate-500 mt-2">
        点击按钮后会通过智慧助教悬浮窗弹出测试消息。实际使用时，AI 会自动在合适时机弹出教学建议。
      </p>
    </div>

    <!-- 建议历史 -->
    <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-white">建议历史</h3>
        <button
          v-if="suggestions.length"
          @click="clearHistory"
          class="text-xs text-slate-400 hover:text-white"
        >
          清空
        </button>
      </div>
      <div v-if="suggestions.length === 0" class="text-center text-slate-500 py-8">
        暂无建议记录
      </div>
      <div v-else class="space-y-3">
        <div
          v-for="(s, i) in suggestions"
          :key="i"
          class="bg-slate-900/60 rounded-lg p-3 border border-slate-700"
        >
          <div class="flex items-center gap-2 mb-1">
            <span
              class="text-xs px-2 py-0.5 rounded"
              :class="{
                'bg-rose-500/15 text-rose-200': s.priority === 'high',
                'bg-amber-500/15 text-amber-200': s.priority === 'medium',
                'bg-slate-700 text-slate-300': s.priority === 'low'
              }"
            >
              {{ s.priority === 'high' ? '重要' : s.priority === 'medium' ? '建议' : '提示' }}
            </span>
            <span class="text-xs text-slate-500">{{ s.time }}</span>
          </div>
          <div class="text-sm text-slate-200">{{ s.content }}</div>
        </div>
      </div>
    </div>

    <!-- 功能说明 -->
    <div class="mt-6 bg-slate-800/50 rounded-xl p-5 border border-slate-700/50">
      <h3 class="text-sm font-semibold text-slate-300 mb-2">智慧助教功能说明</h3>
      <ul class="text-xs text-slate-400 space-y-1 list-disc list-inside">
        <li>实时分析用户学习行为，自动弹出个性化教学建议</li>
        <li>支持截图查词（Ctrl+Shift+S）和划词查词（Ctrl+Shift+C）</li>
        <li>WebSocket 长连接确保低延迟推送</li>
        <li>建议分为重要/建议/提示三级优先级</li>
      </ul>
    </div>
  </div>
</template>
