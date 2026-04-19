/**
 * @fileoverview 语音对话状态管理 (Voice Store)
 * @description 管理语音对话页面的核心业务逻辑和状态。
 *              负责协调 WebSocket 通信、音频录制/播放、对话历史记录以及 UI 状态更新。
 */

import { defineStore } from 'pinia';
import { ref } from 'vue';
import { voiceSocket } from '../services/voice-socket';
import { audioManager } from '../services/audio-manager';
import { ConfigService } from '../services/config';

export const useVoiceStore = defineStore('voice', () => {
  const getCurrentUserId = (): number | undefined => {
    try {
      const raw = localStorage.getItem('auth_user');
      if (!raw) return undefined;
      const user = JSON.parse(raw) as { id?: number | string };
      const id = Number(user?.id);
      if (!Number.isFinite(id) || id <= 0) return undefined;
      return id;
    } catch {
      return undefined;
    }
  };

  // ============ 状态定义 ============
  
  /** 是否正在录音 (用户正在说话) */
  const isRecording = ref(false);
  /** 是否正在处理中 (等待 AI 响应) */
  const isProcessing = ref(false);
  /** AI 是否正在说话 (播放音频中) */
  const isSpeaking = ref(false);
  /** WebSocket 连接状态 (响应式引用) */
  const isConnected = voiceSocket.isConnected;
  
  /** 当前选择的语言 */
  const currentLanguage = ref('zh-CN');
  /** 当前选择的对话场景 */
  const currentScenario = ref('daily');
  
  /** 状态栏显示的文本 */
  const statusText = ref('就绪');
  /** 状态栏显示的类型 (决定颜色和图标) */
  const statusType = ref<'success' | 'processing' | 'listening' | 'speaking' | 'error'>('success');

  /** 对话历史记录列表 */
  const currentDialogue = ref<Array<{ role: 'user' | 'assistant', content: string }>>([]);

  // ws-v1 连接上下文
  const sessionId = ref(`desktop_${Math.random().toString(16).slice(2)}`);
  const conversationId = ref(`conv_${Date.now().toString(16)}`);
  const currentRequestId = ref<string | null>(null);
  const autoCaptureEnabled = ref(false);
  const speechThreshold = ref(420);

  // Ensure we only register one WS message handler.
  let wsUnsubscribe: (() => void) | null = null;
  let hasInitialized = false;

  // ============ 核心方法 ============

  /**
   * 初始化语音服务
   * 建立 WebSocket 连接并注册消息监听器。
   */
  const init = () => {
    // 注册一次消息处理器（重复注册会导致消息被处理多次）
    if (hasInitialized) return;
    hasInitialized = true;
    wsUnsubscribe = voiceSocket.onMessage(handleMessage);
    void ensureConnectedWsV1();
  };

  const ensureConnectedWsV1 = async () => {
    if (isConnected.value) return;
    try {
      const cfg: any = await ConfigService.getConfig();
      let backendUrl = String(cfg?.backend?.wsUrl || cfg?.backendUrl || 'localhost:8012');
      // Guard: avoid accidentally connecting to the frontend dev server (e.g. localhost:8000).
      try {
        const host = String(window?.location?.host || '');
        if (backendUrl === host || /:(8000)\b/.test(backendUrl)) {
          backendUrl = 'localhost:8012';
        }
      } catch {}
      voiceSocket.connectWsV1({
        backendUrl,
        sessionId: sessionId.value,
        conversationId: conversationId.value,
        userId: getCurrentUserId(),
      });
    } catch (e) {
      console.warn('ws-v1 connect failed, falling back to legacy connect', e);
      voiceSocket.connect();
    }
  };

  const waitForConnected = async (timeoutMs: number = 5000) => {
    if (isConnected.value) return;
    const start = Date.now();
    while (!isConnected.value) {
      if (Date.now() - start > timeoutMs) throw new Error('WebSocket connect timeout');
      await new Promise((r) => setTimeout(r, 50));
    }
  };

  /**
   * 添加一条新的对话消息
   * @param role - 角色 ('user' 或 'assistant')
   * @param content - 消息内容
   */
  const addMessage = (role: 'user' | 'assistant', content: string) => {
    currentDialogue.value.push({ role, content });
  };

  /**
   * 追加内容到最后一条 AI 消息 (用于流式输出)
   * @param token - 新生成的文本片段
   */
  const appendToLastAssistantMessage = (token: string) => {
    const lastMsg = currentDialogue.value[currentDialogue.value.length - 1];
    if (lastMsg && lastMsg.role === 'assistant') {
      lastMsg.content += token;
    } else {
      addMessage('assistant', token);
    }
  };

  /**
   * 处理 WebSocket 接收到的消息
   * 根据消息类型分发到不同的处理逻辑。
   */
  const handleMessage = (msg: any) => {
    // ws-v1 (backend_fastapi) event envelope: {type, seq, ts, session_id, conversation_id, request_id, payload}
    if (msg && typeof msg.type === 'string' && msg.type === msg.type.toUpperCase()) {
      const t = msg.type;
      const payload = msg.payload || {};
      const rid = String(msg.request_id || '');

      switch (t) {
        case 'TASK_STARTED': {
          // Ignore connection-level TASK_STARTED({message:connected})
          if (payload?.task === 'voice_audio') {
            setStatus('正在聆听...', 'listening');
          }
          return;
        }
        case 'ASR_PARTIAL': {
          if (payload?.text) {
            setStatus(`识别中: ${String(payload.text)}`, 'listening');
          }
          return;
        }
        case 'ASR_FINAL': {
          const text = String(payload?.text || '');
          if (text) addMessage('user', text);
          if (testIsRunning.value) {
            testAsrText.value = text;
            testMetrics.value.asr_latency_ms =
              typeof payload?.asr_latency_ms === 'number' ? payload.asr_latency_ms : null;
          }
          setStatus(text ? `识别: ${text}` : '识别完成', 'processing');
          isProcessing.value = true;
          return;
        }
        case 'LLM_TOKEN': {
          const delta = String(payload?.text || '');
          if (delta) {
            isProcessing.value = true;
            appendToLastAssistantMessage(delta);
            if (testIsRunning.value) {
              testLlmText.value += delta;
              if (typeof payload?.first_token_latency_ms === 'number') {
                testMetrics.value.llm_first_token_latency_ms = payload.first_token_latency_ms;
              }
            }
          }
          return;
        }
        case 'LLM_RESULT': {
          const markdown = String(payload?.markdown || payload?.text || '');
          if (markdown) {
            const lastMsg = currentDialogue.value[currentDialogue.value.length - 1];
            if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.content) {
              lastMsg.content = markdown;
            } else if (!lastMsg || lastMsg.role !== 'assistant') {
              addMessage('assistant', markdown);
            }
          }
          if (testIsRunning.value) {
            testLlmText.value = markdown;
            testMetrics.value.llm_latency_ms =
              typeof payload?.response_latency_ms === 'number' ? payload.response_latency_ms : null;
            testMetrics.value.llm_first_token_latency_ms =
              typeof payload?.first_token_latency_ms === 'number' ? payload.first_token_latency_ms : testMetrics.value.llm_first_token_latency_ms;
          }
          setStatus('正在合成语音...', 'processing');
          isProcessing.value = true;
          return;
        }
        case 'TTS_CHUNK':
        case 'TTS_RESULT': {
          const b64 = String(payload?.data_b64 || payload?.audio_base64 || '');
          if (testIsRunning.value) {
            testTtsState.value = `已收到${t === 'TTS_CHUNK' ? '音频分片' : '最终音频'}`
            testMetrics.value.tts_synthesis_ms =
              typeof payload?.tts_synthesis_ms === 'number' ? payload.tts_synthesis_ms : testMetrics.value.tts_synthesis_ms;
            testMetrics.value.tts_total_ms =
              typeof payload?.tts_total_ms === 'number' ? payload.tts_total_ms : testMetrics.value.tts_total_ms;
          }
          if (b64) {
            setStatus('正在回复...', 'speaking');
            isSpeaking.value = true;
            isProcessing.value = false;
            // ws-v1 sends wav bytes
            void audioManager.playWavChunk(b64);
          }
          return;
        }
        case 'TASK_ABORTED': {
          if (rid && rid === currentRequestId.value) {
            audioManager.stopPlayback();
            isSpeaking.value = false;
            isProcessing.value = false;
            currentRequestId.value = null;
            setStatus('已打断', 'success');
          }
          return;
        }
        case 'TASK_FINISHED': {
          if (rid && rid === currentRequestId.value) {
            isProcessing.value = false;
            currentRequestId.value = null;
            isSpeaking.value = false;
            if (testIsRunning.value && payload?.pipeline_metrics) {
              const metrics = payload.pipeline_metrics as Record<string, unknown>;
              testMetrics.value.asr_latency_ms =
                typeof metrics.asr_latency_ms === 'number' ? metrics.asr_latency_ms : testMetrics.value.asr_latency_ms;
              testMetrics.value.llm_latency_ms =
                typeof metrics.llm_latency_ms === 'number' ? metrics.llm_latency_ms : testMetrics.value.llm_latency_ms;
              testMetrics.value.llm_first_token_latency_ms =
                typeof metrics.llm_first_token_latency_ms === 'number'
                  ? metrics.llm_first_token_latency_ms
                  : testMetrics.value.llm_first_token_latency_ms;
              testMetrics.value.tts_synthesis_ms =
                typeof metrics.tts_synthesis_ms === 'number' ? metrics.tts_synthesis_ms : testMetrics.value.tts_synthesis_ms;
              testMetrics.value.tts_total_ms =
                typeof metrics.tts_total_ms === 'number' ? metrics.tts_total_ms : testMetrics.value.tts_total_ms;
              testMetrics.value.total_roundtrip_ms =
                typeof metrics.total_roundtrip_ms === 'number' ? metrics.total_roundtrip_ms : testMetrics.value.total_roundtrip_ms;
            }
            if ((payload?.ok ?? true) === false) {
              setStatus('任务已结束（取消/失败）', 'error');
            } else if (payload?.asr_only) {
              setStatus('完成', 'success');
            } else {
              setStatus('完成', 'success');
            }
          }
          return;
        }
        case 'ERROR': {
          const message = String(payload?.message || 'unknown error');
          setStatus(`错误: ${message}`, 'error');
          isProcessing.value = false;
          return;
        }
        default:
          return;
      }
    }

    switch (msg.type) {
      case 'vad_status':
        // VAD (语音活动检测) 状态变更
        if (msg.status === 'speaking') {
          setStatus('检测到语音', 'listening');
          // 用户开始说话时，打断 AI 的播放
          audioManager.stopPlayback();
          voiceSocket.send({ type: 'interrupt' });
          isSpeaking.value = false;
        } else {
          setStatus('语音结束，处理中...', 'processing');
        }
        break;
      case 'asr_result':
        // 收到语音转写结果
        setStatus(`识别: ${msg.text}`, 'success');
        addMessage('user', msg.text);
        break;
      case 'llm_token':
        // 收到 LLM 生成的文本片段 (流式)
        appendToLastAssistantMessage(msg.content);
        break;
      case 'tts_audio':
        // 收到 TTS 生成的音频分片
        if (msg.data) {
          setStatus('正在回复...', 'speaking');
          isSpeaking.value = true;
          isProcessing.value = false;
          audioManager.playChunk(msg.data);
        }
        break;
      case 'error':
        // 收到错误消息
        setStatus(`错误: ${msg.message}`, 'error');
        isProcessing.value = false;
        break;
    }
  };

  /**
   * 更新状态栏显示
   * @param text - 状态文本
   * @param type - 状态类型
   */
  const setStatus = (text: string, type: 'success' | 'processing' | 'listening' | 'speaking' | 'error') => {
    statusText.value = text;
    statusType.value = type;
  };

  /**
   * 启动自定义会话
   * 
   * 初始化一个新的会话上下文，设置语言和提示词，并播放开场白。
   * 
   * @param config - 会话配置对象
   */
  const startCustomSession = async (config: {
    systemPrompt: string;
    openingText: string;
    openingAudio: string;
    language: string;
    scenario?: string;
  }) => {
    // Ensure WS handler is registered before any server events arrive.
    init();
    if (!isConnected.value) {
      await ensureConnectedWsV1();
    }

    // 重置状态
    currentDialogue.value = [];
    currentLanguage.value = config.language;
    currentScenario.value = config.scenario || currentScenario.value;
    autoCaptureEnabled.value = true;
    
    // 添加开场白消息
    addMessage('assistant', config.openingText);
    
    // 播放开场白音频
    if (config.openingAudio) {
      isSpeaking.value = true;
      setStatus('正在回复...', 'speaking');
      // openingAudio uses base64(wav bytes)
      void audioManager.playWavChunk(config.openingAudio).finally(() => {
        // 这是“开场白”本地播放，不会收到 TASK_FINISHED；需要自行复位。
        if (!isRecording.value && !isProcessing.value) {
          isSpeaking.value = false;
          setStatus('就绪', 'success');
        }
      });
    }

    // ws-v1: 写入对话上下文（system prompt），供后端在 LLM 生成时使用。
    if (voiceSocket.isWsV1()) {
      const ctxRid = `ctx_${Date.now().toString(16)}`;
      voiceSocket.sendWsV1Event(
        'CONTEXT_SET',
        {
          system_prompt: config.systemPrompt,
          language: config.language,
          scenario: config.scenario || currentScenario.value,
          user_id: getCurrentUserId(),
        },
        ctxRid
      );
    } else {
      // legacy-stream 才发送 init_session
      voiceSocket.send({
        type: 'init_session',
        config: {
          systemPrompt: config.systemPrompt,
          language: config.language,
          scenario: config.scenario || currentScenario.value,
        }
      });
    }

    // 会话启动后直接进入“自动聆听”模式。
    await startRecording();
  };

  /**
   * 停止会话
   * 停止录音，发送停止指令，清空对话记录。
   */
  const stopSession = () => {
    stopRecording();
    if (!voiceSocket.isWsV1()) {
      voiceSocket.send({ type: 'stop_session' });
    }
    currentDialogue.value = [];
    setStatus('就绪', 'success');

    if (wsUnsubscribe) {
      wsUnsubscribe();
      wsUnsubscribe = null;
      hasInitialized = false;
    }
  };

  /**
   * 开始录音（向后端发送音频流，由后端 SeamlessM4T 进行 ASR）
   *
   * 流程：
   * 1. 通过 WebSocket 发送 AUDIO_START 建立请求上下文。
   * 2. 持续录音，将 Int16 PCM 数据通过 AUDIO_CHUNK_BIN 发送到后端。
   * 3. 后端 VAD 检测到语音结束后自动进行 ASR，并通过 ASR_FINAL 事件返回文本。
   * 4. 后端在同一条音频请求内继续执行 LLM 与 TTS，并通过事件流返回结果与指标。
   */
  const startRecording = async () => {
    // Ensure WS handler is registered before any server events arrive.
    init();
    if (!isConnected.value) {
      await ensureConnectedWsV1();
      await waitForConnected(6000);
    }

    const rid = `audio_${Date.now().toString(16)}`;
    currentRequestId.value = rid;

    try {
      isRecording.value = true;
      autoCaptureEnabled.value = true;
      setStatus('正在聆听...', 'listening');

      const langMap: Record<string, string> = {
        'English': 'en',
        'Japanese': 'ja',
        'Chinese': 'zh',
        'French': 'fr',
      };
      const lang = langMap[currentLanguage.value] || currentLanguage.value || 'auto';

      // 发送 AUDIO_START 建立音频流上下文
      voiceSocket.startAudio(rid, {
        sample_rate: 16000,
        channels: 1,
        encoding: 'pcm_s16le',
        language: lang,
        vad_enabled: true,
        vad_mode: 2,
        vad_silence_ms: 800,
      });

      await audioManager.startRecordingForBackend({
        requestId: rid,
        onChunk: (data) => {
          // 使用二进制模式发送音频 chunk（更高效）
          voiceSocket.sendAudioChunkWsV1(rid, data, true);
        },
      });

    } catch (e) {
      console.error(e);
      setStatus('无法启动录音', 'error');
      isRecording.value = false;
      currentRequestId.value = null;
    }
  };

  /**
   * 停止录音
   */
  const stopRecording = () => {
    autoCaptureEnabled.value = false;
    isRecording.value = false;
    audioManager.stopRecordingForBackend();
    // 发送 AUDIO_END 通知后端收句
    const rid = currentRequestId.value;
    if (rid) {
      voiceSocket.endAudio(rid);
    }
    currentRequestId.value = null;
    isProcessing.value = false;
    setStatus('已暂停自动聆听', 'success');
  };

  /**
   * 切换录音状态 (开始/停止)
   */
  const toggleRecording = () => {
    if (isRecording.value) {
      stopRecording();
    } else {
      void startRecording();
    }
  };

  // ============ 纯本地 ASR 调试模式（不依赖后端）============
  const localAsrText = ref('');
  const localVadSpeaking = ref(false);
  const localBargeInCount = ref(0);

  // ============ ASR+LLM+TTS 端到端测试模式（需后端，TTS 正常播放）============
  const testAsrText = ref('');
  const testLlmText = ref('');
  const testIsRunning = ref(false);
  const testTtsState = ref('');
  const testMetrics = ref<Record<string, number | null>>({
    asr_latency_ms: null,
    llm_latency_ms: null,
    llm_first_token_latency_ms: null,
    tts_synthesis_ms: null,
    tts_total_ms: null,
    total_roundtrip_ms: null,
  });

  const startAsrLlmTest = async () => {
    try {
      testIsRunning.value = true;
      testAsrText.value = '';
      testLlmText.value = '';
      testTtsState.value = '';
      testMetrics.value = {
        asr_latency_ms: null,
        llm_latency_ms: null,
        llm_first_token_latency_ms: null,
        tts_synthesis_ms: null,
        tts_total_ms: null,
        total_roundtrip_ms: null,
      };
      isProcessing.value = false;
      setStatus('ASR+LLM+TTS 测试模式：等待语音...', 'listening');

      // 走完整 ASR -> LLM -> TTS 流程，测试面板只负责展示文本与延迟指标。
      await startRecording();
    } catch (e) {
      console.error(e);
      setStatus('无法启动 ASR+LLM+TTS 测试', 'error');
      testIsRunning.value = false;
    }
  };

  const stopAsrLlmTest = () => {
    testIsRunning.value = false;
    stopRecording();
    setStatus('ASR+LLM+TTS 测试已停止', 'success');
  };

  const startLocalAsrTest = async () => {
    try {
      isRecording.value = true;
      localAsrText.value = '';
      localVadSpeaking.value = false;
      localBargeInCount.value = 0;
      setStatus('本地 ASR 测试中...', 'listening');

      await audioManager.startRecordingWithAsr({
        language: currentLanguage.value,
        speechThreshold: speechThreshold.value,
        silenceMs: 700,
        minSpeechMs: 300,
        onVadChange: (speaking) => {
          localVadSpeaking.value = speaking;
          if (speaking) {
            setStatus('检测到语音', 'listening');
            // 模拟打断：如果 AI 正在播放，则计数打断
            if (isSpeaking.value) {
              localBargeInCount.value += 1;
            }
            audioManager.stopPlayback();
            isSpeaking.value = false;
            isProcessing.value = false;
          } else {
            setStatus('语音结束，识别中...', 'processing');
            isProcessing.value = true;
          }
        },
        onResult: (text) => {
          localAsrText.value = text;
          if (!text) {
            isProcessing.value = false;
            setStatus('未识别到语音，继续聆听...', 'listening');
            return;
          }
          addMessage('user', text);
          setStatus(`识别: ${text}`, 'success');
          isProcessing.value = false;
          // 纯本地模式：不发送给后端
        },
        onError: (err) => {
          console.error('ASR error:', err);
          setStatus(`识别错误: ${err}`, 'error');
          isProcessing.value = false;
        },
      });
    } catch (e) {
      console.error(e);
      setStatus('无法启动本地 ASR 测试', 'error');
      isRecording.value = false;
    }
  };

  const stopLocalAsrTest = () => {
    isRecording.value = false;
    audioManager.stopRecordingWithAsr();
    isProcessing.value = false;
    localVadSpeaking.value = false;
    setStatus('本地 ASR 测试已停止', 'success');
  };

  return {
    // State
    isRecording,
    isProcessing,
    isSpeaking,
    isConnected,
    autoCaptureEnabled,
    statusText,
    statusType,
    currentLanguage,
    currentScenario,
    currentDialogue,
    localAsrText,
    localVadSpeaking,
    localBargeInCount,
    testAsrText,
    testLlmText,
    testIsRunning,
    testTtsState,
    testMetrics,

    // Actions
    init,
    toggleRecording,
    startCustomSession,
    stopSession,
    startLocalAsrTest,
    stopLocalAsrTest,
    startAsrLlmTest,
    stopAsrLlmTest,
  };
});
