<script setup lang="ts">
/**
 * @fileoverview 设置视图组件 (SettingsView)
 * @description 管理应用的全局配置，包括常规设置、音频设备选择和 AI 模型参数。
 *              配置数据会自动持久化到本地存储。
 */

import { ref, onMounted, watch } from 'vue';
import { getDefaultBackendUrl, getDefaultBackendWsHost } from '../services/backend-url';
import { ConfigService, type AppConfig, type SystemConfig } from '../services/config';

// --- 状态管理 ---

/** 应用配置对象 */
const settings = ref<AppConfig>({
  general: { theme: 'dark', language: 'zh-CN', autoUpdate: true },
  audio: { inputDevice: 'default', outputDevice: 'default', volume: 80 },
  ai: { model: 'local-model', temperature: 0.7, voice: 'alloy' },
  backend: { url: getDefaultBackendUrl(), wsUrl: getDefaultBackendWsHost() }
});

/** 后端返回的可用本地模型列表 */
const availableModels = ref<string[]>([]);

/** 后端系统配置快照 */
const systemConfig = ref<SystemConfig | null>(null);

/** 可用的音频输入设备列表 (麦克风) */
const inputDevices = ref<MediaDeviceInfo[]>([]);

/** 可用的音频输出设备列表 (扬声器) */
const outputDevices = ref<MediaDeviceInfo[]>([]);

/** 当前激活的设置面板 ID */
const activeSection = ref('general');

/** 设置面板导航菜单 */
const sections = [
  { id: 'general', label: '常规设置', icon: '⚙️' },
  { id: 'audio', label: '音频设置', icon: '🔊' },
  { id: 'ai', label: 'AI 模型', icon: '🤖' },
  { id: 'backend', label: '后端连接', icon: '🔌' },
  { id: 'about', label: '关于', icon: 'ℹ️' }
];

// --- 生命周期 ---

onMounted(async () => {
  try {
    // 加载保存的配置
    const config = await ConfigService.getConfig();
    // 合并默认配置，确保所有字段都存在
    settings.value = { ...settings.value, ...config };

    // 兜底确保 backend 字段存在
    if (!settings.value.backend) {
      settings.value.backend = { url: getDefaultBackendUrl(), wsUrl: getDefaultBackendWsHost() };
    } else {
      settings.value.backend = {
        url: settings.value.backend.url || getDefaultBackendUrl(),
        wsUrl: settings.value.backend.wsUrl || getDefaultBackendWsHost()
      };
    }

    // 拉取后端运行态配置（包含可用模型列表）
    const sys = await ConfigService.getSystemConfig();
    systemConfig.value = sys;
    const backendModels = (sys?.models as any)?.available;
    if (Array.isArray(backendModels)) {
      availableModels.value = backendModels.filter((x) => typeof x === 'string' && x.trim());
    }

    // 使用“后端当前场景模型 -> 主模型 -> default”的优先级回填 UI。
    const sceneChat = String((sys?.models as any)?.scene?.chat || '').trim();
    const primary = String((sys?.models as any)?.primary || '').trim();
    const fallback = String((sys?.models as any)?.default || '').trim();
    const chosen = sceneChat || primary || fallback || settings.value.ai.model;
    settings.value.ai.model = chosen;

    // 加载音频设备列表
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
      const devices = await navigator.mediaDevices.enumerateDevices();
      inputDevices.value = devices.filter(d => d.kind === 'audioinput');
      outputDevices.value = devices.filter(d => d.kind === 'audiooutput');
    }
  } catch (e) {
    console.error('Failed to load config or devices', e);
  }
});

// --- 监听器 ---

/**
 * 监听配置变化并自动保存
 * 
 * 当 settings 对象发生任何变化时，调用 ConfigService.setConfig 进行持久化。
 * deep: true 确保可以监听到嵌套属性的变化。
 */
watch(settings, async (newSettings) => {
  await ConfigService.setConfig(newSettings);
}, { deep: true });

// 当用户切换“对话模型”时，实时同步到后端配置：
// - 设为 primary
// - 同步更新 chat 场景模型
watch(
  () => settings.value.ai.model,
  async (model) => {
    const val = String(model || '').trim();
    if (!val) return;
    try {
      await ConfigService.updateSystemConfig({
        models: {
          primary: val,
          scene: {
            chat: val,
          },
        },
      } as any);
    } catch (e) {
      console.warn('同步后端模型配置失败', e);
    }
  }
);
</script>

<template>
  <div class="p-8 h-full flex flex-col">
    <h2 class="text-2xl font-bold text-white mb-8">设置</h2>
    
    <div class="flex-1 flex bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
      <!-- Sidebar -->
      <div class="w-64 bg-gray-900/50 border-r border-gray-700 p-4">
        <div class="space-y-1">
          <button
            v-for="section in sections"
            :key="section.id"
            @click="activeSection = section.id"
            class="w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-left transition-colors"
            :class="activeSection === section.id ? 'bg-indigo-600 text-white' : 'text-gray-400 hover:bg-gray-800 hover:text-white'"
          >
            <span>{{ section.icon }}</span>
            <span>{{ section.label }}</span>
          </button>
        </div>
      </div>

      <!-- Content -->
      <div class="flex-1 p-8 overflow-y-auto">
        <div v-if="activeSection === 'general'" class="space-y-6">
          <h3 class="text-xl font-semibold text-white mb-6">常规设置</h3>
          
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-400 mb-2">界面主题</label>
              <select v-model="settings.general.theme" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent">
                <option value="dark">深色模式</option>
                <option value="light">浅色模式</option>
                <option value="system">跟随系统</option>
              </select>
            </div>
            
            <div class="flex items-center justify-between py-4 border-t border-gray-700">
              <div>
                <div class="text-white font-medium">自动更新</div>
                <div class="text-sm text-gray-500">自动下载并安装最新版本</div>
              </div>
              <button 
                class="w-12 h-6 rounded-full transition-colors relative"
                :class="settings.general.autoUpdate ? 'bg-indigo-600' : 'bg-gray-700'"
                @click="settings.general.autoUpdate = !settings.general.autoUpdate"
              >
                <div 
                  class="absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform"
                  :class="settings.general.autoUpdate ? 'translate-x-6' : 'translate-x-0'"
                ></div>
              </button>
            </div>
          </div>
        </div>

        <div v-if="activeSection === 'audio'" class="space-y-6">
          <h3 class="text-xl font-semibold text-white mb-6">音频设置</h3>
          
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-400 mb-2">输入设备 (麦克风)</label>
              <select v-model="settings.audio.inputDevice" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent">
                <option value="default">默认设备</option>
                <option v-for="device in inputDevices" :key="device.deviceId" :value="device.deviceId">
                  {{ device.label || `Microphone ${device.deviceId.slice(0, 5)}...` }}
                </option>
              </select>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-400 mb-2">输出设备 (扬声器)</label>
              <select v-model="settings.audio.outputDevice" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent">
                <option value="default">默认设备</option>
                <option v-for="device in outputDevices" :key="device.deviceId" :value="device.deviceId">
                  {{ device.label || `Speaker ${device.deviceId.slice(0, 5)}...` }}
                </option>
              </select>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-400 mb-2">音量 ({{ settings.audio.volume }}%)</label>
              <input 
                type="range" 
                v-model.number="settings.audio.volume" 
                min="0" 
                max="100" 
                class="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              >
            </div>
          </div>
        </div>

        <div v-if="activeSection === 'ai'" class="space-y-6">
          <h3 class="text-xl font-semibold text-white mb-6">AI 模型设置</h3>
          
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-400 mb-2">对话模型</label>
              <select v-model="settings.ai.model" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent">
                <option
                  v-for="model in availableModels"
                  :key="model"
                  :value="model"
                >
                  {{ model }}
                </option>
                <option v-if="availableModels.length === 0" :value="settings.ai.model">
                  {{ settings.ai.model || 'local-model' }}
                </option>
              </select>
              <div class="text-xs text-gray-500 mt-1">模型列表来自后端 /api/system/config 的可用本地模型探测结果</div>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-400 mb-2">随机性 (Temperature: {{ settings.ai.temperature }})</label>
              <div class="flex items-center space-x-4">
                <span class="text-xs text-gray-500">精确</span>
                <input 
                  type="range" 
                  v-model.number="settings.ai.temperature" 
                  min="0" 
                  max="2" 
                  step="0.1"
                  class="flex-1 h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                >
                <span class="text-xs text-gray-500">创意</span>
              </div>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-400 mb-2">TTS 音色</label>
              <select v-model="settings.ai.voice" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent">
                <option value="alloy">Alloy (中性)</option>
                <option value="echo">Echo (男声)</option>
                <option value="fable">Fable (英式)</option>
                <option value="onyx">Onyx (深沉)</option>
                <option value="nova">Nova (活力)</option>
                <option value="shimmer">Shimmer (清澈)</option>
              </select>
            </div>
          </div>
        </div>

        <div v-if="activeSection === 'backend'" class="space-y-6">
          <h3 class="text-xl font-semibold text-white mb-6">后端连接</h3>

          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-400 mb-2">HTTP API 地址</label>
              <input
                v-model="settings.backend.url"
                type="text"
                placeholder="http://localhost:8012"
                class="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
              <div class="text-xs text-gray-500 mt-1">用于登录、系统配置、提示词等 HTTP 接口</div>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-400 mb-2">语音 WebSocket 后端 (host:port)</label>
              <input
                v-model="settings.backend.wsUrl"
                type="text"
                placeholder="localhost:8012"
                class="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
              <div class="text-xs text-gray-500 mt-1">用于 ws-v1：例如 localhost:8012（无需写 ws://）</div>
            </div>
          </div>
        </div>

        <div v-if="activeSection === 'about'" class="space-y-6">
          <h3 class="text-xl font-semibold text-white mb-6">关于</h3>
          <div class="text-gray-400 space-y-2">
            <p>AI Language Learning Platform</p>
            <p>Version: 5.0.0 (Preview)</p>
            <p>© 2025 AI for Foreign Language Learning Team</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
