<script setup lang="ts">
/**
 * @fileoverview 语音对话视图组件 (VoiceView)
 * @description 提供语音对话的核心交互界面。
 */

import { computed, ref, onMounted, onUnmounted } from 'vue';
import { useVoiceStore } from '../stores/voice';
import { VoiceService } from '../services/voice';
import { AuthService } from '../services/auth';
import { ClassroomService } from '../services/classroom';
import WaterBall from '../components/WaterBall.vue';
import { Loader2, Mic, MicOff, PhoneOff, FlaskConical } from 'lucide-vue-next';

const voiceStore = useVoiceStore();

const step = ref<'input' | 'review' | 'active'>('input');
const scenarioInput = ref('');
const targetLanguage = ref('English');
const generatedPrompt = ref('');
const isGenerating = ref(false);
const isStarting = ref(false);
const isDev = import.meta.env.DEV;
const classroomSessionId = ref('');
const currentSpeakerId = ref<number | null>(null);
const speakerStudentId = ref('');
const classroomStatus = ref('');
const isClassroomBusy = ref(false);
const currentUser = computed(() => AuthService.getCurrentUser());
const canControlSpeaker = computed(() => {
  const role = currentUser.value?.role;
  return role === 'teacher' || role === 'admin';
});

const normalizePositiveId = (value: string) => {
  const id = Number(String(value || '').trim());
  return Number.isFinite(id) && id > 0 ? id : null;
};

const saveClassroomSession = async () => {
  classroomStatus.value = '';
  const id = normalizePositiveId(classroomSessionId.value);
  if (!id) {
    voiceStore.setClassroomSessionId('');
    currentSpeakerId.value = null;
    classroomStatus.value = '已退出课堂模式';
    return;
  }
  voiceStore.setClassroomSessionId(String(id));
  classroomStatus.value = '课堂模式已保存，开始会话时生效';
  await refreshCurrentSpeaker();
};

const refreshCurrentSpeaker = async () => {
  const id = normalizePositiveId(classroomSessionId.value);
  if (!id) return;
  isClassroomBusy.value = true;
  try {
    const state = await ClassroomService.getCurrentSpeaker(id);
    currentSpeakerId.value = state.current_speaker_id;
    classroomStatus.value = state.current_speaker_id
      ? `当前发言学生：#${state.current_speaker_id}`
      : '当前未指定发言学生';
  } catch (e: any) {
    const status = e?.response?.status;
    if (status === 401) classroomStatus.value = '请先登录';
    else if (status === 403) classroomStatus.value = '无权访问该课堂';
    else classroomStatus.value = '课堂状态读取失败';
  } finally {
    isClassroomBusy.value = false;
  }
};

const setCurrentSpeaker = async () => {
  const sessionId = normalizePositiveId(classroomSessionId.value);
  const studentId = normalizePositiveId(speakerStudentId.value);
  if (!sessionId || !studentId) {
    classroomStatus.value = '请输入课堂 session ID 和学生 ID';
    return;
  }
  isClassroomBusy.value = true;
  try {
    voiceStore.setClassroomSessionId(String(sessionId));
    const state = await ClassroomService.setCurrentSpeaker(sessionId, studentId);
    currentSpeakerId.value = state.current_speaker_id;
    classroomStatus.value = `已允许学生 #${state.current_speaker_id} 发言`;
  } catch (e: any) {
    const detail = String(e?.response?.data?.detail || '');
    if (detail.includes('not enrolled')) classroomStatus.value = '该学生不在此课堂';
    else if (e?.response?.status === 403) classroomStatus.value = '只有本课堂教师或管理员可切换发言人';
    else classroomStatus.value = '设置发言人失败';
  } finally {
    isClassroomBusy.value = false;
  }
};

const clearCurrentSpeaker = async () => {
  const sessionId = normalizePositiveId(classroomSessionId.value);
  if (!sessionId) return;
  isClassroomBusy.value = true;
  try {
    const state = await ClassroomService.clearCurrentSpeaker(sessionId);
    currentSpeakerId.value = state.current_speaker_id;
    classroomStatus.value = '已清空当前发言人';
  } catch (e: any) {
    if (e?.response?.status === 403) classroomStatus.value = '只有本课堂教师或管理员可清空发言人';
    else classroomStatus.value = '清空发言人失败';
  } finally {
    isClassroomBusy.value = false;
  }
};

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

const handleStart = async () => {
  isStarting.value = true;
  try {
    const result = await VoiceService.startSession(generatedPrompt.value);
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

const handleRewrite = () => {
  step.value = 'input';
};

const handleEndSession = () => {
  voiceStore.stopSession();
  step.value = 'input';
};

onMounted(() => {
  classroomSessionId.value = voiceStore.classroomSessionId;
  voiceStore.init();
  if (classroomSessionId.value) void refreshCurrentSpeaker();
});

onUnmounted(() => {
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
              class="flex-1 py-3 rounded-xl border transition-all font-medium"
              :class="targetLanguage === 'English' ? 'bg-indigo-600 border-indigo-500 text-white' : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'"
            >
              English
            </button>
            <button
              @click="targetLanguage = 'Japanese'"
              class="flex-1 py-3 rounded-xl border transition-all font-medium"
              :class="targetLanguage === 'Japanese' ? 'bg-indigo-600 border-indigo-500 text-white' : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'"
            >
              Japanese
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

        <div class="rounded-xl border border-gray-700 bg-gray-800/70 p-4">
          <div class="mb-3 flex items-center justify-between">
            <div>
              <div class="text-sm font-semibold text-gray-200">课堂模式</div>
              <div class="mt-1 text-xs text-gray-500">填写课堂 session ID 后，本次语音会话会进入课堂轮流发言控制。</div>
            </div>
            <button
              type="button"
              class="rounded-md border border-gray-600 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-60"
              :disabled="isClassroomBusy || !classroomSessionId"
              @click="refreshCurrentSpeaker"
            >
              刷新
            </button>
          </div>

          <div class="grid gap-3 md:grid-cols-[1fr_auto]">
            <input
              v-model="classroomSessionId"
              class="rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-indigo-500"
              placeholder="课堂 session ID，可留空"
              type="number"
              min="1"
              @keyup.enter="saveClassroomSession"
            />
            <button
              type="button"
              class="rounded-md bg-gray-700 px-4 py-2 text-sm text-white hover:bg-gray-600 disabled:opacity-60"
              :disabled="isClassroomBusy"
              @click="saveClassroomSession"
            >
              保存
            </button>
          </div>

          <div v-if="canControlSpeaker" class="mt-3 grid gap-3 md:grid-cols-[1fr_auto_auto]">
            <input
              v-model="speakerStudentId"
              class="rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-indigo-500"
              placeholder="当前发言学生 ID"
              type="number"
              min="1"
              @keyup.enter="setCurrentSpeaker"
            />
            <button
              type="button"
              class="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60"
              :disabled="isClassroomBusy"
              @click="setCurrentSpeaker"
            >
              允许发言
            </button>
            <button
              type="button"
              class="rounded-md border border-gray-600 px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 disabled:opacity-60"
              :disabled="isClassroomBusy || !classroomSessionId"
              @click="clearCurrentSpeaker"
            >
              清空
            </button>
          </div>

          <div class="mt-3 text-xs" :class="classroomStatus ? 'text-gray-300' : 'text-gray-500'">
            {{ classroomStatus || (currentSpeakerId ? `当前发言学生：#${currentSpeakerId}` : '未启用课堂模式') }}
          </div>
        </div>

        <button
          @click="handleGenerate"
          :disabled="isGenerating || !scenarioInput"
          class="w-full py-4 bg-gradient-to-r from-indigo-600 to-purple-600 rounded-xl text-white font-bold text-lg shadow-lg hover:shadow-indigo-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
        >
          <Loader2 v-if="isGenerating" class="w-5 h-5 mr-2 animate-spin" />
          {{ isGenerating ? 'Analyzing...' : 'Generate Prompt' }}
        </button>

        <!-- Dev debug panels -->
        <div v-if="isDev" class="mt-8 p-4 bg-gray-800/60 border border-gray-700 rounded-xl">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold text-gray-300 flex items-center gap-2">
              <Mic class="w-4 h-4" /> 本地 ASR 调试
            </h3>
            <button
              @click="voiceStore.isRecording ? voiceStore.stopLocalAsrTest() : voiceStore.startLocalAsrTest()"
              class="px-3 py-1.5 text-xs rounded-lg font-medium transition-colors"
              :class="voiceStore.isRecording ? 'bg-red-500/20 text-red-300 hover:bg-red-500/30' : 'bg-green-500/20 text-green-300 hover:bg-green-500/30'"
            >
              {{ voiceStore.isRecording ? '停止' : '开始' }}
            </button>
          </div>
          <div class="grid grid-cols-3 gap-3 text-xs">
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">识别结果</div>
              <div class="text-white font-medium min-h-[1.25rem]">{{ voiceStore.localAsrText || '—' }}</div>
            </div>
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">VAD</div>
              <div class="font-medium" :class="voiceStore.localVadSpeaking ? 'text-green-400' : 'text-gray-400'">
                {{ voiceStore.localVadSpeaking ? 'Speaking' : 'Silent' }}
              </div>
            </div>
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">打断</div>
              <div class="text-white font-medium">{{ voiceStore.localBargeInCount }}</div>
            </div>
          </div>
        </div>

        <div v-if="isDev" class="mt-6 p-4 bg-gray-800/60 border border-indigo-500/30 rounded-xl">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold text-indigo-300 flex items-center gap-2">
              <FlaskConical class="w-4 h-4" /> 端到端测试
            </h3>
            <button
              @click="voiceStore.testIsRunning ? voiceStore.stopAsrLlmTest() : voiceStore.startAsrLlmTest()"
              class="px-3 py-1.5 text-xs rounded-lg font-medium transition-colors"
              :class="voiceStore.testIsRunning ? 'bg-red-500/20 text-red-300 hover:bg-red-500/30' : 'bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30'"
            >
              {{ voiceStore.testIsRunning ? '停止' : '开始' }}
            </button>
          </div>
          <div class="grid grid-cols-2 gap-3 text-xs">
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">ASR</div>
              <div class="text-white font-medium min-h-[3rem] whitespace-pre-wrap">{{ voiceStore.testAsrText || '—' }}</div>
            </div>
            <div class="bg-gray-900/60 rounded-lg p-3">
              <div class="text-gray-500 mb-1">LLM</div>
              <div class="text-white font-medium min-h-[3rem] whitespace-pre-wrap">{{ voiceStore.testLlmText || '—' }}</div>
            </div>
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
          Rewrite
        </button>
        <button
          @click="handleStart"
          :disabled="isStarting"
          class="flex-[2] py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold shadow-lg transition-all flex items-center justify-center"
        >
          <Loader2 v-if="isStarting" class="w-5 h-5 mr-2 animate-spin" />
          {{ isStarting ? 'Starting...' : 'Start Session' }}
        </button>
      </div>
    </div>

    <!-- Step 3: Active Session -->
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
          <div class="bg-black/30 backdrop-blur-md rounded-lg px-4 py-3 border border-white/10">
            <h2 class="text-lg font-bold text-white mb-1">{{ scenarioInput }}</h2>
            <div class="flex items-center space-x-2">
              <span
                class="w-2 h-2 rounded-full transition-colors duration-500"
                :class="{
                  'bg-green-500': voiceStore.statusType === 'success',
                  'bg-yellow-500': voiceStore.statusType === 'processing',
                  'bg-red-500': voiceStore.statusType === 'listening' || voiceStore.statusType === 'speaking',
                  'bg-gray-500': voiceStore.statusType === 'error'
                }"
              ></span>
              <p class="text-sm text-gray-300 font-medium tracking-wide">{{ voiceStore.statusText }}</p>
            </div>
          </div>

          <button
            @click="handleEndSession"
            class="p-2 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white rounded-lg border border-white/10 transition-colors"
            title="End Session"
          >
            <PhoneOff class="w-5 h-5" />
          </button>
        </div>

        <!-- Controls -->
        <div class="flex justify-center items-end pb-8 pointer-events-auto relative z-20">
          <button
            @click="voiceStore.toggleMute"
            class="w-20 h-20 rounded-full flex items-center justify-center transition-all duration-300 shadow-lg hover:scale-105"
            :class="voiceStore.isRecording
              ? 'bg-red-500 hover:bg-red-600 shadow-red-500/50'
              : voiceStore.isMuted
                ? 'bg-gray-600 hover:bg-gray-500 shadow-gray-500/30'
                : 'bg-indigo-500 hover:bg-indigo-600 shadow-indigo-500/50'"
          >
            <Mic v-if="voiceStore.isRecording" class="w-8 h-8 text-white" />
            <MicOff v-else class="w-8 h-8 text-white" />
          </button>
        </div>

        <!-- Dialogue History -->
        <div class="absolute top-24 bottom-32 left-8 w-80 pointer-events-auto overflow-y-auto space-y-4 pr-2 custom-scrollbar">
          <div
            v-for="(msg, index) in voiceStore.currentDialogue"
            :key="index"
            class="p-3 rounded-lg backdrop-blur-md border border-white/10 text-sm transition-opacity duration-300"
            :class="msg.role === 'user' ? 'bg-indigo-600/40 ml-8' : 'bg-gray-800/40 mr-8'"
          >
            <div class="text-xs opacity-50 mb-1 font-medium">{{ msg.role === 'user' ? 'You' : 'AI' }}</div>
            <div class="text-white">{{ msg.content }}</div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>
