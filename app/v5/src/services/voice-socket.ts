/**
 * @fileoverview 语音 WebSocket 服务模块
 * @description 封装 WebSocket 连接管理，用于处理实时的语音流传输和信令控制。
 *              提供自动重连、消息分发和状态管理功能。
 */

import { ref } from 'vue';

/** 消息处理回调函数类型定义 */
type MessageHandler = (msg: any) => void;

type VoiceSocketProtocol = 'legacy-stream' | 'ws-v1';

type WsV1ConnectOptions = {
  backendUrl: string; // e.g. "127.0.0.1:8012" or "localhost:8012"
  sessionId: string;
  conversationId: string;
  userId?: number;
};

/**
 * 语音 WebSocket 服务类
 * 
 * 负责维护与后端语音服务的长连接。
 * 支持发送 JSON 信令和二进制音频数据。
 */
class VoiceSocketService {
  private ws: WebSocket | null = null;
  // 默认 WebSocket 地址，生产环境应从配置读取
  private url: string = 'ws://localhost:8012/stream';

  private protocol: VoiceSocketProtocol = 'legacy-stream';
  private wsV1: WsV1ConnectOptions | null = null;
  private lastSeq: number | null = null;
  
  // 重连机制相关参数
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  
  // 消息订阅者列表
  private messageHandlers: MessageHandler[] = [];
  
  // 响应式连接状态，供 Vue 组件使用
  public isConnected = ref(false);

  constructor() {
    // 构造函数中暂不自动连接，由组件显式调用 connect
  }

  public isWsV1(): boolean {
    return this.protocol === 'ws-v1';
  }

  /**
   * 建立 WebSocket 连接
   * 
   * @param {string} [url] - 可选的连接地址，若不提供则使用默认值
   */
  public connect(url?: string) {
    if (url) this.url = url;
    
    // 避免重复连接
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;

    console.log('正在连接 WebSocket:', this.url);
    this.ws = new WebSocket(this.url);
    this.ws.binaryType = 'arraybuffer'; // 设置二进制类型为 ArrayBuffer，以便处理音频流

    // 连接成功回调
    this.ws.onopen = () => {
      console.log('WebSocket 连接成功');
      this.isConnected.value = true;
      this.reconnectAttempts = 0; // 重置重连计数
      // legacy-stream 模式下发送初始化握手；ws-v1 模式不发送，避免服务端把它当未知消息回显/落库。
      if (this.protocol === 'legacy-stream') {
        this.send({ type: 'page_mounted', data: { page: 'voice-dialogue-v5' } });
      }
    };

    // 收到消息回调
    this.ws.onmessage = (event) => {
      try {
        // 目前假设后端只发送 JSON 格式的控制消息
        // 如果后续有下行音频流，需在此处判断 event.data 类型
        const data = JSON.parse(event.data);

        // ws-v1: track last_seq for reconnect replay.
        if (this.protocol === 'ws-v1' && typeof data?.seq === 'number') {
          const s = Number(data.seq);
          if (Number.isFinite(s)) {
            this.lastSeq = this.lastSeq == null ? s : Math.max(this.lastSeq, s);
          }
        }
        this.notifyHandlers(data);
      } catch (e) {
        console.error('WebSocket 消息解析失败:', e);
      }
    };

    // 连接关闭回调
    this.ws.onclose = () => {
      console.log('WebSocket 连接关闭');
      this.isConnected.value = false;
      this.handleReconnect(); // 触发重连机制
    };

    // 连接错误回调
    this.ws.onerror = (err) => {
      console.error('WebSocket 发生错误:', err);
      this.isConnected.value = false;
    };
  }

  /**
   * 发送数据
   * 
   * @param {any} data - 要发送的数据。可以是 JSON 对象（自动序列化）或二进制数据（ArrayBuffer/Int16Array）。
   */
  public send(data: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      if (data instanceof ArrayBuffer || data instanceof Int16Array) {
        this.ws.send(data);
      } else {
        this.ws.send(JSON.stringify(data));
      }
    }
  }

  /**
   * 以 backend_fastapi 的 `/ws/v1` 协议连接（支持 last_seq 回放 + JSON 事件 + 二进制音频帧）。
   */
  public connectWsV1(options: WsV1ConnectOptions) {
    this.protocol = 'ws-v1';
    this.wsV1 = options;
    const url = this.buildWsV1Url();
    this.connect(url);
  }

  /**
   * 发送 ws-v1 JSON 事件（后端_fastapi 约定：{type, request_id, payload}）。
   */
  public sendWsV1Event(type: string, payload: Record<string, any> = {}, requestId?: string) {
    this.send({ type, request_id: requestId, payload });
  }

  public startAudio(requestId: string, payload: Record<string, any>) {
    this.sendWsV1Event('AUDIO_START', payload, requestId);
  }

  public endAudio(requestId: string) {
    this.send({ type: 'AUDIO_END', request_id: requestId });
  }

  /**
   * ws-v1 音频上行：优先使用 `AUDIO_CHUNK_BIN`（JSON 头 + 下一帧二进制）。
   * 如需兼容老服务端，可设置 preferBinary=false，走 `AUDIO_CHUNK(data_b64)`。
   */
  public sendAudioChunkWsV1(requestId: string, chunk: ArrayBuffer | Int16Array, preferBinary: boolean = true) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    const bytes =
      chunk instanceof ArrayBuffer
        ? new Uint8Array(chunk)
        : new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength);

    if (preferBinary) {
      // JSON header first
      this.send({ type: 'AUDIO_CHUNK_BIN', request_id: requestId, payload: {} });
      // then raw bytes as the next WS binary frame
      this.ws.send(bytes);
      return;
    }

    const data_b64 = arrayBufferToBase64(bytes);
    this.send({ type: 'AUDIO_CHUNK', request_id: requestId, payload: { data_b64 } });
  }

  /**
   * 注册消息监听器
   * 
   * @param {MessageHandler} handler - 回调函数
   * @returns {Function} 取消订阅的函数
   */
  public onMessage(handler: MessageHandler) {
    this.messageHandlers.push(handler);
    // 返回一个用于注销该监听器的函数
    return () => {
      this.messageHandlers = this.messageHandlers.filter(h => h !== handler);
    };
  }

  /**
   * 通知所有订阅者
   */
  private notifyHandlers(msg: any) {
    this.messageHandlers.forEach(h => h(msg));
  }

  /**
   * 处理断线重连
   * 采用指数退避算法 (Exponential Backoff) 计算重连延迟。
   */
  private handleReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
      console.log(`将在 ${delay}ms 后尝试重连...`);
      setTimeout(() => {
        this.reconnectAttempts++;
        if (this.protocol === 'ws-v1' && this.wsV1) {
          this.connect(this.buildWsV1Url());
        } else {
          this.connect();
        }
      }, delay);
    }
  }

  /**
   * 主动断开连接
   */
  public disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  private buildWsV1Url(): string {
    if (!this.wsV1) return this.url;
    const backendUrl = normalizeBackendHost(String(this.wsV1.backendUrl || '').trim());
    const sessionId = encodeURIComponent(String(this.wsV1.sessionId || 'anonymous'));
    const conversationId = encodeURIComponent(String(this.wsV1.conversationId || 'conv'));
    const userId =
      typeof this.wsV1.userId === 'number' && this.wsV1.userId > 0
        ? `&user_id=${encodeURIComponent(String(this.wsV1.userId))}`
        : '';
    const lastSeq = this.lastSeq == null ? '' : `&last_seq=${encodeURIComponent(String(this.lastSeq))}`;
    return `ws://${backendUrl}/ws/v1?session_id=${sessionId}&conversation_id=${conversationId}${userId}${lastSeq}`;
  }
}

function normalizeBackendHost(input: string): string {
  // Accept "host:port" or a full URL like "http://host:port" / "ws://host:port".
  return input.replace(/^https?:\/\//, '').replace(/^wss?:\/\//, '').replace(/\/$/, '');
}

function arrayBufferToBase64(bytes: Uint8Array): string {
  // Avoid call-stack limits by chunking.
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const sub = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...sub);
  }
  return btoa(binary);
}

// 导出单例实例
export const voiceSocket = new VoiceSocketService();
