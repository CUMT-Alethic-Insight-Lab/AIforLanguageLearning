/**
 * @fileoverview 实时助教状态管理 (Assistant Store)
 * @description 管理两类悬浮窗：
 *              1. 查词入口悬浮窗（截图/划词后手动触发查词 → HTTP API → 结果悬浮窗）
 *              2. 智慧助教悬浮窗（RTA WebSocket 在 LLM 指定位置弹出结果）
 */

import { defineStore } from 'pinia';
import { ref } from 'vue';
import { rtaSocket } from '../services/rta-socket';
import { VocabularyService } from '../services/vocabulary';

export interface AssistantSuggestion {
  type: 'suggestion';
  priority: 'high' | 'medium' | 'low';
  content: string;
  has_audio: boolean;
  audio_base64?: string;
  audio_format?: string;
}

export const useAssistantStore = defineStore('assistant', () => {
  // ── 状态 ──
  const isEnabled = ref(true);
  const isConnected = rtaSocket.isConnected;
  const lastSuggestion = ref<AssistantSuggestion | null>(null);
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  let unsubMessage: (() => void) | null = null;
  let unsubScreenshot: (() => void) | null = null;
  let unsubTextSelect: (() => void) | null = null;
  let unsubOverlayAction: (() => void) | null = null;

  // 缓存最近一次的截图/文本，供入口悬浮窗点击后使用
  let lastImageBase64: string | null = null;
  let lastSelectedText: string | null = null;

  // ── 初始化 ──
  const init = () => {
    if (typeof window === 'undefined' || !window.api) return;

    // 1. 建立 RTA WebSocket（智慧助教链路）
    connectRta();

    // 2. 监听系统截图事件（Ctrl+Shift+S）→ 显示查词入口悬浮窗
    unsubScreenshot = window.api.onSystemScreenshot?.((data: any) => {
      if (!isEnabled.value) return;
      lastImageBase64 = data.imageBase64;
      lastSelectedText = null;
      window.api?.smartOverlayShow?.({
        mode: 'entry',
        title: '检测到截图',
        imageBase64: data.imageBase64,
        actionLabel: '查词',
        actionPayload: { source: 'screenshot' },
      });
    });

    // 3. 监听系统划词/文本事件（Ctrl+Shift+C）→ 显示查词入口悬浮窗
    unsubTextSelect = window.api.onSystemTextSelect?.((data: any) => {
      if (!isEnabled.value) return;
      lastImageBase64 = null;
      lastSelectedText = data.text;
      const preview = data.text.length > 80 ? data.text.slice(0, 80) + '...' : data.text;
      window.api?.smartOverlayShow?.({
        mode: 'entry',
        title: '检测到文本',
        textPreview: preview,
        actionLabel: '查词',
        actionPayload: { source: 'text', fullText: data.text },
      });
    });

    // 4. 监听悬浮窗操作事件（用户点击"查词"或"查看详情"）
    unsubOverlayAction = window.api.onSmartOverlayAction?.((action: any) => {
      handleOverlayAction(action);
    });

    // 5. 监听 RTA 后端消息（智慧助教链路）
    unsubMessage = rtaSocket.onMessage((msg: any) => {
      handleRtaMessage(msg);
    });

    // 6. 心跳
    heartbeatTimer = setInterval(() => {
      if (rtaSocket.isConnected.value) rtaSocket.sendHeartbeat();
    }, 30000);
  };

  const cleanup = () => {
    unsubScreenshot?.();
    unsubTextSelect?.();
    unsubOverlayAction?.();
    unsubMessage?.();
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
    rtaSocket.disconnect();
  };

  // ── RTA 连接 ──
  const connectRta = () => {
    let userId = 1;
    let username = 'teacher';
    try {
      const raw = localStorage.getItem('auth_user');
      if (raw) { const u = JSON.parse(raw); userId = u.id || 1; username = u.username || 'teacher'; }
    } catch { /* ignore */ }

    let backendWsUrl = 'localhost:8012';
    try {
      const cfgRaw = localStorage.getItem('app_config');
      if (cfgRaw) {
        const cfg = JSON.parse(cfgRaw);
        backendWsUrl = cfg.backend?.wsUrl || cfg.backend?.url?.replace(/^https?:\/\//, '') || 'localhost:8012';
      }
    } catch { /* ignore */ }

    rtaSocket.connect({ backendWsUrl, userId, username });
  };

  // ── 处理悬浮窗用户操作 ──
  const handleOverlayAction = async (action: any) => {
    const payload = action?.payload || {};

    // 查词入口：用户点击了"查词"
    if (action?.type === 'entry-action' && payload.source) {
      // 先显示 loading
      window.api?.smartOverlayShow?.({
        mode: 'loading',
        title: '查词中...',
        content: '正在调用 AI 分析，请稍候',
        hideFooter: true,
      });

      try {
        let result;
        if (payload.source === 'screenshot' && lastImageBase64) {
          result = await VocabularyService.queryOCR(lastImageBase64);
        } else if (payload.source === 'text' && lastSelectedText) {
          result = await VocabularyService.query(lastSelectedText);
        } else {
          throw new Error('没有可查询的内容');
        }

        // 格式化查词结果为悬浮窗文本
        const defs = result.definitions?.map((d: any) =>
          `• ${d.meaning}${d.example ? `（例：${d.example}）` : ''}`
        ).join('\n') || result.meaning || '暂无释义';

        const extras: string[] = [];
        if (result.cefrLevel) extras.push(`CEFR: ${result.cefrLevel}`);
        if (result.schoolStage) extras.push(`学段: ${result.schoolStage}`);
        if (result.examTags?.length) extras.push(`考点: ${result.examTags.join(', ')}`);

        const content = `<b style="color:#fff;font-size:15px">${result.word}</b>\n${defs}${extras.length ? '\n\n' + extras.join(' | ') : ''}`;

        window.api?.smartOverlayShow?.({
          mode: 'result',
          title: '查词结果',
          content,
          priority: 'medium',
          actionLabel: '去词库',
          actionPayload: { type: 'vocab-result', word: result.word },
        });
      } catch (err: any) {
        window.api?.smartOverlayShow?.({
          mode: 'result',
          title: '查词失败',
          content: err?.message || '服务暂时不可用，请检查后端连接',
          priority: 'low',
          hideFooter: true,
        });
      }
      return;
    }

    // 结果悬浮窗：用户点击了"查看详情"或"去词库"
    if (action?.type === 'action') {
      console.log('[Assistant] Result action:', payload);
      // 可扩展：跳转到词库详情页、教师仪表盘等
    }
  };

  // ── 处理 RTA 消息（智慧助教） ──
  const handleRtaMessage = (msg: any) => {
    if (msg.type === 'suggestion') {
      const suggestion: AssistantSuggestion = {
        type: 'suggestion',
        priority: msg.priority || 'medium',
        content: msg.content || '',
        has_audio: msg.has_audio || false,
        audio_base64: msg.audio_base64,
        audio_format: msg.audio_format,
      };
      lastSuggestion.value = suggestion;

      // 支持 LLM 指定位置（x, y），否则默认右上角
      const overlayPayload: any = {
        mode: 'result',
        title: suggestion.priority === 'high' ? '重要提醒' : suggestion.priority === 'medium' ? '教学建议' : '轻量提示',
        content: suggestion.content,
        priority: suggestion.priority,
        actionLabel: '查看详情',
        actionPayload: { type: 'rta-suggestion', data: suggestion },
      };
      if (typeof msg.x === 'number') overlayPayload.x = msg.x;
      if (typeof msg.y === 'number') overlayPayload.y = msg.y;

      window.api?.smartOverlayShow?.(overlayPayload);

      if (suggestion.has_audio && suggestion.audio_base64) {
        playAudio(suggestion.audio_base64, suggestion.audio_format || 'wav');
      }
    } else if (msg.type === 'error') {
      window.api?.smartOverlayShow?.({
        mode: 'result',
        title: '助教提示',
        content: msg.message || '服务暂时不可用',
        priority: 'low',
        hideFooter: true,
      });
    }
  };

  // ── 音频播放 ──
  const playAudio = (base64: string, format: string) => {
    try {
      const mime = format === 'mp3' ? 'audio/mpeg' : 'audio/wav';
      const audio = new Audio(`data:${mime};base64,${base64}`);
      audio.play().catch((err) => console.warn('[Assistant] Audio play failed:', err));
    } catch (e) {
      console.error('[Assistant] Audio decode failed:', e);
    }
  };

  // ── 手动触发（供 UI 按钮调用）──
  const showEntryOverlay = (payload: {
    title: string;
    imageBase64?: string;
    textPreview?: string;
    actionLabel?: string;
  }) => {
    window.api?.smartOverlayShow?.({
      mode: 'entry',
      ...payload,
      actionPayload: { source: 'manual' },
    });
  };

  const showResultOverlay = (payload: {
    title: string;
    content: string;
    priority?: 'high' | 'medium' | 'low';
    x?: number;
    y?: number;
  }) => {
    window.api?.smartOverlayShow?.({
      mode: 'result',
      ...payload,
    });
  };

  const toggleEnabled = () => {
    isEnabled.value = !isEnabled.value;
    if (!isEnabled.value) window.api?.smartOverlayClose?.();
  };

  return {
    isEnabled,
    isConnected,
    lastSuggestion,
    init,
    cleanup,
    showEntryOverlay,
    showResultOverlay,
    toggleEnabled,
  };
});
