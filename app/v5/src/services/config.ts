/**
 * @fileoverview 配置服务模块 (Configuration Service)
 * @description 负责管理应用的所有配置项，包括通用设置、音频设置、AI 模型参数以及后端连接信息。
 *              该服务支持从 Electron 主进程获取配置（优先），或回退到本地存储（LocalStorage）和默认值。
 */

import api from './api';
import { getDefaultBackendUrl, getDefaultBackendWsHost, normalizeBackendUrl, normalizeBackendWsHost } from './backend-url';

/**
 * 应用配置接口定义
 * 描述了前端应用可配置的所有选项结构。
 */
export interface AppConfig {
  /** 通用设置 */
  general: {
    /** 主题设置：深色、浅色或跟随系统 */
    theme: 'dark' | 'light' | 'system';
    /** 界面语言代码 (如 'zh-CN', 'en-US') */
    language: string;
    /** 是否开启自动更新 */
    autoUpdate: boolean;
  };
  /** 音频设备与音量设置 */
  audio: {
    /** 输入设备 ID (麦克风) */
    inputDevice: string;
    /** 输出设备 ID (扬声器) */
    outputDevice: string;
    /** 系统音量百分比 (0 - 100) */
    volume: number;
  };
  /** AI 模型与语音参数设置 */
  ai: {
    /** 使用的大语言模型名称 */
    model: string;
    /** 模型温度参数 (控制随机性) */
    temperature: number;
    /** TTS 语音合成的角色 ID */
    voice: string;
  };
  /** 后端服务连接配置 */
  backend: {
    /** HTTP API 服务地址 */
    url: string;
    /** WebSocket 服务地址 */
    wsUrl: string;
  };
}

/**
 * 系统配置接口定义 (后端返回的完整系统配置)
 */
export interface SystemConfig {
  port: number;
  llmEndpoint: string;
  models: {
    default: string;
    primary?: string;
    available?: string[];
    scene?: {
      chat?: string;
      vocab?: string;
      essay?: string;
    };
  };
  prompts: any;
  ocr: any;
  tts: any;
  asr: any;
}

function normalizeConfig(cfg: AppConfig): AppConfig {
  const next = { ...cfg, backend: { ...cfg.backend } }

  next.backend.url = normalizeBackendUrl(next.backend?.url)
  next.backend.wsUrl = normalizeBackendWsHost(next.backend?.wsUrl || next.backend.url)

  return next
}

export const ConfigService = {
  // 合并默认/本地/IPC 配置（尽量保持结构完整，避免 settings 页面字段丢失）
  mergeConfig(base: AppConfig, patch: Partial<AppConfig> | any): AppConfig {
    const next: AppConfig = { ...base };
    if (patch?.general) next.general = { ...next.general, ...patch.general };
    if (patch?.audio) next.audio = { ...next.audio, ...patch.audio };
    if (patch?.ai) next.ai = { ...next.ai, ...patch.ai };
    if (patch?.backend) {
      next.backend = {
        url: String(patch.backend?.url || next.backend?.url || ''),
        wsUrl: String(patch.backend?.wsUrl || next.backend?.wsUrl || '')
      };
    }
    return next;
  },

  /**
   * 获取应用配置
   * 
   * 获取策略：
   * 1. 优先尝试通过 Electron IPC 从主进程获取配置 (适用于桌面端)。
   * 2. 如果失败或不在 Electron 环境，尝试从 LocalStorage 读取缓存配置。
   * 3. 如果都没有，返回默认配置。
   * 
   * @returns {Promise<AppConfig>} 应用配置对象
   */
  async getConfig(): Promise<AppConfig> {
    const defaults: AppConfig = {
      general: { theme: 'dark', language: 'zh-CN', autoUpdate: true },
      audio: { inputDevice: 'default', outputDevice: 'default', volume: 80 },
      ai: { model: 'local-model', temperature: 0.7, voice: 'alloy' },
      backend: { url: getDefaultBackendUrl(), wsUrl: getDefaultBackendWsHost() }
    };

    // 本地缓存（用于 api.ts 动态 baseURL 等）
    let storedConfig: Partial<AppConfig> | null = null;
    try {
      const stored = localStorage.getItem('app_config');
      if (stored) storedConfig = JSON.parse(stored);
    } catch {
      storedConfig = null;
    }

    // 1. 尝试从 Electron 主进程获取
    if (window.api && window.api.getConfig) {
      try {
        const ipcCfg = await window.api.getConfig();
        // 允许 IPC 只返回部分字段；这里与 defaults/localStorage 做合并。
        const merged = normalizeConfig(this.mergeConfig(this.mergeConfig(defaults, storedConfig ?? {}), ipcCfg ?? {}));
        localStorage.setItem('app_config', JSON.stringify(merged));
        return merged;
      } catch (e) {
        console.warn('从主进程获取配置失败，将使用本地回退方案', e);
      }
    }
    
    // 2. 回退方案：读取 LocalStorage
    if (storedConfig) {
      const merged = normalizeConfig(this.mergeConfig(defaults, storedConfig));
      localStorage.setItem('app_config', JSON.stringify(merged));
      return merged;
    }

    const normalizedDefaults = normalizeConfig(defaults);
    localStorage.setItem('app_config', JSON.stringify(normalizedDefaults));
    return normalizedDefaults;
  },

  async setConfig(config: AppConfig): Promise<void> {
    const normalized = normalizeConfig(config);
    if (window.api && window.api.setConfig) {
      try {
        await window.api.setConfig(normalized);
      } catch (e) {
        console.warn('Failed to set config in main process', e);
      }
    }
    localStorage.setItem('app_config', JSON.stringify(normalized));
  },

  async getSystemConfig(): Promise<SystemConfig> {
    const response = await api.get<{ success: boolean; data: SystemConfig }>('/api/system/config');
    // @ts-ignore
    if (response.success) {
      // @ts-ignore
      return response.data;
    }
    throw new Error('Failed to get system config');
  },

  async updateSystemConfig(config: Partial<SystemConfig>): Promise<void> {
    await api.post('/api/system/config', config);
  }
};
