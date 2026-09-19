/**
 * @fileoverview 语音 WebSocket 服务模块
 * @description 封装与后端语音服务的长连接（legacy-stream 与 ws-v1 双协议），
 *              支持二进制音频帧上行、last_seq 断线回放。
 *              连接管理/重连/消息分发由 BaseWsService 提供。
 */

import { buildWsUrl } from './backend-url';
import { BaseWsService } from './ws-base';

type VoiceSocketProtocol = 'legacy-stream' | 'ws-v1';

type WsV1ConnectOptions = {
  backendUrl: string; // e.g. "127.0.0.1:8012" or "localhost:8012"
  sessionId: string;
  conversationId: string;
  classroomSessionId?: number | string | null;
  userId?: number;
};

class VoiceSocketService extends BaseWsService {
  private protocol: VoiceSocketProtocol = 'legacy-stream';
  private wsV1: WsV1ConnectOptions | null = null;
  private lastSeq: number | null = null;

  constructor() {
    // 构造函数中暂不自动连接，由组件显式调用 connect
    super('WS');
    // 默认 WebSocket 地址，生产环境应从配置读取
    this.url = 'ws://localhost:8012/stream';
  }

  public isWsV1(): boolean {
    return this.protocol === 'ws-v1';
  }

  /**
   * 建立 WebSocket 连接
   *
   * @param {string} [url] - 可选的连接地址，若不提供则使用现有值
   */
  public connect(url?: string) {
    if (url) this.url = url;
    this.doConnect();
  }

  /**
   * 发送数据
   *
   * @param {any} data - JSON 对象（自动序列化）或二进制数据（ArrayBuffer/Int16Array）
   */
  public send(data: any) {
    if (data instanceof ArrayBuffer || data instanceof Int16Array) {
      this.sendRaw(data);
    } else {
      this.sendRaw(JSON.stringify(data));
    }
  }

  /**
   * 以 backend_fastapi 的 `/ws/v1` 协议连接（支持 last_seq 回放 + JSON 事件 + 二进制音频帧）。
   */
  public connectWsV1(options: WsV1ConnectOptions) {
    this.protocol = 'ws-v1';
    this.wsV1 = options;
    this.url = this.buildWsV1Url();
    this.doConnect();
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
  public sendAudioChunkWsV1(
    requestId: string,
    chunk: ArrayBuffer | Int16Array,
    preferBinary: boolean = true
  ) {
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
   * Force-reconnect with new WsV1 options (e.g. new conversationId).
   * Clears all callbacks on the old socket to prevent spurious handleReconnect,
   * then immediately opens a fresh connection with the new options.
   */
  public reconnectWsV1(options: WsV1ConnectOptions) {
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.close();
      this.ws = null;
    }
    this.isConnected.value = false;
    this.reconnectAttempts = 0;
    this.lastSeq = null;
    this.connectWsV1(options);
  }

  // ── BaseWsService 钩子 ──

  protected onSocketCreated(ws: WebSocket): void {
    // 二进制类型为 ArrayBuffer，以便处理音频流
    ws.binaryType = 'arraybuffer';
  }

  protected onOpen(): void {
    // legacy-stream 模式下发送初始化握手；ws-v1 模式不发送，避免服务端把它当未知消息回显/落库。
    if (this.protocol === 'legacy-stream') {
      this.send({ type: 'page_mounted', data: { page: 'voice-dialogue-v5' } });
    }
  }

  protected onMessageData(data: any): void {
    // ws-v1: track last_seq for reconnect replay.
    if (this.protocol === 'ws-v1' && typeof data?.seq === 'number') {
      const s = Number(data.seq);
      if (Number.isFinite(s)) {
        this.lastSeq = this.lastSeq == null ? s : Math.max(this.lastSeq, s);
      }
    }
  }

  protected prepareReconnect(): void {
    if (this.protocol === 'ws-v1' && this.wsV1) {
      this.url = this.buildWsV1Url();
    }
  }

  private buildWsV1Url(): string {
    if (!this.wsV1) return this.url;
    const sessionId = encodeURIComponent(String(this.wsV1.sessionId || 'anonymous'));
    const conversationId = encodeURIComponent(String(this.wsV1.conversationId || 'conv'));
    const token = localStorage.getItem('auth_token');
    const tokenParam = token ? `&token=${encodeURIComponent(token)}` : '';
    const lastSeq =
      this.lastSeq == null ? '' : `&last_seq=${encodeURIComponent(String(this.lastSeq))}`;
    const classroomSessionId = this.wsV1.classroomSessionId;
    const classroomParam = classroomSessionId
      ? `&classroom_session_id=${encodeURIComponent(String(classroomSessionId))}`
      : '';
    return buildWsUrl(
      this.wsV1.backendUrl,
      `/ws/v1?session_id=${sessionId}&conversation_id=${conversationId}${tokenParam}${lastSeq}${classroomParam}`
    );
  }
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
