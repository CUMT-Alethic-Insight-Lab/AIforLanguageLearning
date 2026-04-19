<script setup lang="ts">
/**
 * @fileoverview 语音对话视图组件 (VoiceView)
 * @description 提供语音对话的核心交互界面。
 *              包含三个主要步骤：
 *              1. 输入场景 (Input): 用户输入对话场景描述和选择目标语言。
 *              2. 审查提示词 (Review): 确认或编辑 AI 生成的系统提示词 (System Prompt)。
 *              3. 进行对话 (Active): 启动语音会话，显示水球动画 (WaterBall) 进行实时交互。
 */

import { ref, onMounted, onUnmounted } from 'vue';
import { useVoiceStore } from '../stores/voice';
import { VoiceService } from '../services/voice';
import WaterBall from '../components/WaterBall.vue';

// 引入 Voice Store 用于管理会话状态
const voiceStore = useVoiceStore();

// --- UI 状态管理 ---

/** 当前步骤: 'input' (输入) | 'review' (审查) | 'active' (进行中) */
const step = ref<'input' | 'review' | 'active'>('input');

/** 用户输入的场景描述 */
const scenarioInput = ref('');

/** 目标语言 (默认为英语) */
const targetLanguage = ref('English');

/** 生成的系统提示词 */
const generatedPrompt = ref('');

/** 是否正在生成提示词 */
const isGenerating = ref(false);

/** 是否正在启动会话 */
const isStarting = ref(false);

/** 是否处于开发模式 (用于显示调试面板) */
const isDev = import.meta.env.DEV;

// --- 步骤 1: 生成提示词 ---

/**
 * 处理生成提示词
 * 
 * 调用 VoiceService.generatePrompt 根据用户输入的场景生成系统提示词。
 * 成功后进入 'review' 步骤。
 */
const handleGenerate = async () => {
  if (!scenarioInput.value.trim()) return;
  
  isGenerating.value = true;
  try {
    const prompt = await VoiceService.generatePrompt(scenarioInput.value, targetLanguage.value);
    generatedPrompt.value = prompt;
    step.value = 'review';
  } catch (e) {
    console.error(e);
    alert('生成提示词失败，请重试。');
  } finally {
    isGenerating.value = false;
  }
};

// --- 步骤 2: 确认并启动 ---

/**
 * 处理启动会话
 * 
 * 1. 调用 VoiceService.startSession 获取开场白和音频。
 * 2. 初始化 Voice Store，传入系统提示词、开场白等信息。
 * 3. 进入 'active' 步骤，显示 WaterBall 组件。
 */
const handleStart = async () => {
  isStarting.value = true;
  try {
    const result = await VoiceService.startSession(generatedPrompt.value);
    
    // 使用自定义提示词和开场白初始化 Store
    await voiceStore.startCustomSession({
      systemPrompt: generatedPrompt.value,
      openingText: result.openingText,
      openingAudio: result.openingAudio,
      language: targetLanguage.value,
      scenario: scenarioInput.value
    });
    
    step.value = 'active';
  } catch (e) {
    console.error(e);
    alert('启动会话失败。');
  } finally {
    isStarting.value = false;
  }
};

/**
 * 返回重写场景
 * 
 * 如果用户对生成的提示词不满意，可以返回第一步重新输入场景。
 */
const handleRewrite = () => {
  step.value = 'input';
};

// --- 生命周期钩子 ---

onMounted(() => {
  // 预先初始化语音服务（幂等）：注册 WS 消息处理器并尝试建立连接。
  voiceStore.init();
});

onUnmounted(() => {
  // 组件卸载时停止会话，释放资源
  voiceStore.stopSession();
});
</script>

<template>
  <div class="h-full flex flex-col relative overflow-hidden bg-gray-900">
    
    <!-- Step 1: Input Scenario -->
    <div v-if="step === 'input'" class="flex-1 flex flex-col items-center justify-center p-8 max-w-2xl mx-auto w-full z-20">
      <h1 class="text-3xl font-bold text-white mb-8">Create Your Conversation</h1>
      
      <div class="w-full space-y-6">
        <div>
          <label class="block text-gray-400 text-sm mb-2">Target Language</label>
          <div class="flex space-x-4">
            <button 
              @click="targetLanguage = 'English'"
              class="flex-1 py-3 rounded-xl border transition-all"
              :class="targetLanguage === 'English' ? 'bg-indigo-600 border-indigo-500 text-white' : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'"
            >
              🇺🇸 English
            </button>
            <button 
              @click="targetLanguage = 'Japanese'"
              class="flex-1 py-3 rounded-xl border transition-all"
              :class="targetLanguage === 'Japanese' ? 'bg-indigo-600 border-indigo-500 text-white' : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'"
            >
              🇯🇵 Japanese
            </button>
          </div>
        </div>

        <div>
          <label class="block text-gray-400 text-sm mb-2">Scenario Description</label>
          <textarea
            v-model="scenarioInput"
            class="w-full h-40 bg-gray-800 border border-gray-700 rounded-xl p-4 text-white focus:ring-2 focus:ring-indigo-500 outline-none resize-none"
            placeholder="e.g., Ordering a coffee in a busy Parisian cafe..."
          ></textarea>
        </div>

        <button
          @click="handleGenerate"
          :disabled="isGenerating || !scenarioInput"
          class="w-full py-4 bg-gradient-to-r from-indigo-600 to-purple-600 rounded-xl text-white font-bold text-lg shadow-lg hover:shadow-indigo-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
        >
          <span v-if="isGenerating" class="animate-spin mr-2">⚡</span>
          {{ isGenerating ? 'Analyzing Scenario...' : 'Generate Prompt' }}
        </button>

        <!-- Local ASR Debug Panel (development only) -->
        <div v-if="isDev" class="mt-8 p-4 bg-gray-800/60 border border-gray-700 rounded-xl">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold text-gray-300">🎙 本地 ASR 调试（无需后端）</h3>
            <button
              @click="voiceStore.isRecording ? voiceStore.stopLocalAsrTest() : voiceStore.startLocalAsrTest()"
              class="px-3 py-1.5 text-xs rounded-lg font-medium transition-colors"
              :class="voiceStore.isRecording ? 'bg-red-500/20 text-red-300 hover:bg-red-500/30' : 'bg-green-500/20 text-green-300 hover:bg-green-500/30'"
            >
              {{ voiceStore.isRecording ? '停止测试' : '开始测试' }}
            </button>
          </div>

          <div class="grid grid-cols-3 gap-3 text-xs">
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">识别结果</div>
              <div class="text-white font-medium min-h-[1.25rem]">{{ voiceStore.localAsrText || '—' }}</div>
            </div>
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">VAD 状态</div>
              <div class="font-medium" :class="voiceStore.localVadSpeaking ? 'text-green-400' : 'text-gray-400'">
                {{ voiceStore.localVadSpeaking ? '正在说话' : '静音' }}
              </div>
            </div>
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">打断次数</div>
              <div class="text-white font-medium">{{ voiceStore.localBargeInCount }}</div>
            </div>
          </div>

          <div class="mt-2 text-[10px] text-gray-500">
            状态: {{ voiceStore.statusText }}
          </div>
        </div>

        <!-- ASR+LLM+TTS 端到端测试（development only） -->
        <div v-if="isDev" class="mt-6 p-4 bg-gray-800/60 border border-indigo-500/30 rounded-xl">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold text-indigo-300">🧪 ASR+LLM+TTS 端到端测试（需后端）</h3>
            <button
              @click="voiceStore.testIsRunning ? voiceStore.stopAsrLlmTest() : voiceStore.startAsrLlmTest()"
              class="px-3 py-1.5 text-xs rounded-lg font-medium transition-colors"
              :class="voiceStore.testIsRunning ? 'bg-red-500/20 text-red-300 hover:bg-red-500/30' : 'bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30'"
            >
              {{ voiceStore.testIsRunning ? '停止测试' : '开始测试' }}
            </button>
          </div>

          <div class="grid grid-cols-2 gap-3 text-xs">
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">🎤 ASR 识别结果</div>
              <div class="text-white font-medium min-h-[3rem] whitespace-pre-wrap">{{ voiceStore.testAsrText || '—' }}</div>
            </div>
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">🤖 LLM 回复结果</div>
              <div class="text-white font-medium min-h-[3rem] whitespace-pre-wrap">{{ voiceStore.testLlmText || '—' }}</div>
            </div>
          </div>

          <div class="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs mt-3">
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">🔊 TTS 状态</div>
              <div class="text-white font-medium min-h-[1.25rem]">{{ voiceStore.testTtsState || '等待音频输出' }}</div>
            </div>
            <div class="bg-gray-900/60 rounded-lg p-3" v-for="(val, key) in voiceStore.testMetrics" :key="key">
              <div class="text-gray-500 mb-1">{{ key }}</div>
              <div class="text-white font-medium">{{ val ?? '—' }}</div>
            </div>
          </div>

          <div class="mt-3 text-[10px] text-gray-500">
            说明：测试面板会完整走 ASR → LLM 流式输出 → TTS 播放，不会抑制语音。请同时核对 ASR 识别准确度、LLM 回复质量、TTS 听感，以及 ASR/LLM/TTS/总链路延迟。
          </div>
        </div>
      </div>
    </div>

    <!-- Step 2: Review Prompt -->
    <div v-if="step === 'review'" class="flex-1 flex flex-col items-center justify-center p-8 max-w-3xl mx-auto w-full z-20">
      <h1 class="text-2xl font-bold text-white mb-6">Review System Prompt</h1>
      
      <div class="w-full bg-gray-800 rounded-xl border border-gray-700 p-6 mb-6 relative group">
        <textarea
          v-model="generatedPrompt"
          class="w-full h-64 bg-transparent text-gray-300 font-mono text-sm outline-none resize-none custom-scrollbar"
        ></textarea>
        <div class="absolute top-2 right-2 text-xs text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity">
          Editable
        </div>
      </div>

      <div class="flex space-x-4 w-full">
        <button
          @click="handleRewrite"
          class="flex-1 py-3 bg-gray-700 hover:bg-gray-600 text-white rounded-xl transition-colors"
        >
          Rewrite Scenario
        </button>
        <button
          @click="handleStart"
          :disabled="isStarting"
          class="flex-[2] py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold shadow-lg transition-all flex items-center justify-center"
        >
          <span v-if="isStarting" class="animate-spin mr-2">⏳</span>
          {{ isStarting ? 'Initializing Session...' : 'Confirm & Start' }}
        </button>
      </div>
    </div>

    <!-- Step 3: Active Session (WaterBall) -->
    <div v-if="step === 'active'" class="absolute inset-0 z-0">
      <div id="scene-container" class="absolute inset-0 bg-gradient-to-b from-gray-900 to-gray-800">
        <WaterBall 
          :is-listening="voiceStore.isRecording"
          :is-speaking="voiceStore.isSpeaking"
          :is-processing="voiceStore.isProcessing"
        />
      </div>

      <!-- Active UI Overlay -->
      <div class="relative z-10 h-full flex flex-col justify-between p-8 pointer-events-none">
        <!-- Header -->
        <div class="flex justify-between items-start pointer-events-auto">
          <div class="bg-black/30 backdrop-blur-md rounded-lg p-4 border border-white/10">
            <h2 class="text-xl font-bold text-white mb-1">{{ scenarioInput }}</h2>
            <div class="flex items-center space-x-2">
              <span 
                class="w-2 h-2 rounded-full"
                :class="{
                  'bg-green-500': voiceStore.statusType === 'success',
                  'bg-yellow-500': voiceStore.statusType === 'processing',
                  'bg-red-500': voiceStore.statusType === 'listening' || voiceStore.statusType === 'speaking',
                  'bg-gray-500': voiceStore.statusType === 'error'
                }"
              ></span>
              <p class="text-sm text-gray-300">{{ voiceStore.statusText }}</p>
            </div>
          </div>
          
          <button 
            @click="voiceStore.stopSession(); step = 'input'"
            class="px-4 py-2 bg-red-500/20 hover:bg-red-500/40 text-red-200 rounded-lg border border-red-500/30 transition-colors"
          >
            End Session
          </button>
        </div>

        <!-- Controls -->
        <div class="flex justify-center items-end pb-8 pointer-events-auto relative z-20">
          <button
            @click="voiceStore.toggleRecording"
            class="w-20 h-20 rounded-full flex items-center justify-center transition-all duration-300 shadow-lg hover:scale-105"
            :class="voiceStore.isRecording ? 'bg-orange-500 hover:bg-orange-600 shadow-orange-500/50' : 'bg-indigo-500 hover:bg-indigo-600 shadow-indigo-500/50'"
          >
            <span class="text-3xl">{{ voiceStore.isRecording ? '⏸' : '🎤' }}</span>
          </button>
        </div>

        <div class="absolute bottom-4 left-1/2 -translate-x-1/2 text-xs text-gray-300 bg-black/30 border border-white/10 rounded-full px-3 py-1 pointer-events-none">
          {{ voiceStore.isRecording ? '自动聆听已开启（VAD 自动收句）' : '自动聆听已暂停' }}
        </div>

        <!-- Dialogue History -->
        <div class="absolute top-24 bottom-32 left-8 w-80 pointer-events-auto overflow-y-auto space-y-4 pr-2 custom-scrollbar">
          <div 
            v-for="(msg, index) in voiceStore.currentDialogue" 
            :key="index"
            class="p-3 rounded-lg backdrop-blur-md border border-white/10 text-sm"
            :class="msg.role === 'user' ? 'bg-indigo-600/40 ml-8' : 'bg-gray-800/40 mr-8'"
          >
            <div class="text-xs opacity-50 mb-1">{{ msg.role === 'user' ? 'You' : 'AI' }}</div>
            <div class="text-white">{{ msg.content }}</div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>
