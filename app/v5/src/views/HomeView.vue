<script setup lang="ts">
/**
 * @fileoverview 首页视图组件 (HomeView)
 * @description 应用的默认着陆页，提供单词查询和 OCR 图片识别功能。
 *              用户可以输入文本或粘贴图片进行查询。
 */

import { ref, onMounted, onUnmounted } from 'vue';
import { VocabularyService } from '../services/vocabulary';
import type { VocabularyResult } from '../types/vocabulary';
import VocabularyCard from '../components/VocabularyCard.vue';

// --- 响应式状态 ---

/** 搜索输入框的内容 */
const searchQuery = ref('');

/** 是否正在进行搜索或 OCR 识别 */
const isSearching = ref(false);

/** 搜索结果数据 */
const searchResult = ref<VocabularyResult | null>(null);

/** 错误提示信息 */
const errorMsg = ref('');

const runLookup = async (term: string, options?: { updateInput?: boolean }) => {
  const normalized = String(term || '').trim();
  if (!normalized) return;

  if (options?.updateInput !== false) {
    searchQuery.value = normalized;
  }

  isSearching.value = true;
  errorMsg.value = '';
  searchResult.value = null;

  try {
    const result = await VocabularyService.query(normalized);
    searchResult.value = result;
  } catch (err: any) {
    console.error('Search error:', err);
    errorMsg.value = err?.message || '查询失败，请稍后重试。';
  } finally {
    isSearching.value = false;
  }
};

const handleSearch = async () => {
  await runLookup(searchQuery.value, { updateInput: true });
};

const handleRecommendationLookup = async (word: string) => {
  await runLookup(word, { updateInput: true });
};

/**
 * 处理粘贴事件 (支持图片 OCR)
 * 
 * 监听全局粘贴事件，如果粘贴板中包含图片，则自动进行 OCR 识别。
 * 
 * @param {ClipboardEvent} event - 剪贴板事件对象
 */
const handlePaste = async (event: ClipboardEvent) => {
  const items = event.clipboardData?.items;
  if (!items) return;

  for (const item of items) {
    // 检查是否为图片类型
    if (item.type.indexOf('image') !== -1) {
      const blob = item.getAsFile();
      if (!blob) continue;

      isSearching.value = true;
      errorMsg.value = '';
      searchResult.value = null;
      searchQuery.value = '[正在识别图片...]';

      const reader = new FileReader();
      
      // 读取图片为 Base64 格式
      reader.onload = async (e) => {
        const base64 = e.target?.result as string;
        try {
          const result = await VocabularyService.queryOCR(base64);
          searchResult.value = result;
          searchQuery.value = result.word;
        } catch (err: any) {
          console.error('OCR error:', err);
          errorMsg.value = err?.message || '识图失败，请重试。';
          searchQuery.value = '';
        } finally {
          isSearching.value = false;
        }
      };
      
      reader.readAsDataURL(blob);
      break; // 只处理第一张图片
    }
  }
};

// --- 生命周期钩子 ---

onMounted(() => {
  // 组件挂载时添加粘贴事件监听
  document.addEventListener('paste', handlePaste);
});

onUnmounted(() => {
  // 组件卸载时移除监听，防止内存泄漏
  document.removeEventListener('paste', handlePaste);
});
</script>

<template>
  <div class="h-full flex flex-col p-8 max-w-5xl mx-auto">
    <!-- Input Area -->
    <div class="relative mb-6 flex-shrink-0">
      <input
        v-model="searchQuery"
        @keyup.enter="handleSearch"
        type="text"
        class="w-full px-6 py-4 bg-gray-800 border border-gray-700 rounded-xl text-white text-lg focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/50 outline-none transition-all shadow-lg"
        placeholder="输入单词、短语或直接粘贴图片 (Ctrl+V)..."
      />
      <div class="absolute right-3 top-3 flex items-center space-x-2">
        <span v-if="isSearching" class="text-indigo-400 text-sm animate-pulse mr-2">AI 思考中...</span>
        <button
          @click="handleSearch"
          class="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors font-medium"
          :disabled="isSearching"
        >
          查询
        </button>
      </div>
    </div>

    <!-- Error Message -->
    <div v-if="errorMsg" class="bg-red-900/50 border border-red-700 text-red-200 px-6 py-4 rounded-xl mb-6 flex-shrink-0">
      {{ errorMsg }}
    </div>

    <!-- Result Area (Minimalist Text Box) -->
    <div class="flex-1 bg-gray-900 rounded-xl border border-gray-700 shadow-inner overflow-hidden flex flex-col">
      <div class="flex-1 overflow-y-auto p-6 custom-scrollbar">
        <VocabularyCard
          v-if="searchResult"
          :data="searchResult"
          @lookup-recommendation="handleRecommendationLookup"
        />
        <div v-else class="h-full flex flex-col items-center justify-center text-gray-600 space-y-4">
          <div class="text-6xl opacity-20">⌨️</div>
          <p>等待输入...</p>
        </div>
      </div>
    </div>
  </div>
</template>
