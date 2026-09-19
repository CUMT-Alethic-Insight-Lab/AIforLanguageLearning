/**
 * @fileoverview 实时助教 WebSocket 服务 (RTA Socket)
 * @description 封装与后端 /api/v1/realtime-assistant/ws 的 WebSocket 连接。
 *              连接管理/重连/消息分发由 BaseWsService 提供；
 *              本类负责 RTA URL 构建、离线消息队列与领域事件发送。
 */

import { BaseWsService } from './ws-base';

export interface RtaConnectOptions {
  backendWsUrl: string; // e.g. "localhost:8012"
  userId: number;
  username?: string;
}

class RtaSocketService extends BaseWsService {
  private pendingMessages: any[] = [];

  constructor() {
    super('RTA');
  }

  public connect(options: RtaConnectOptions) {
    const host = options.backendWsUrl.replace(/^wss?:\/\//, '').replace(/\/$/, '');
    const userId = encodeURIComponent(String(options.userId));
    const username = encodeURIComponent(options.username || `user_${options.userId}`);
    this.url = `ws://${host}/api/v1/realtime-assistant/ws?user_id=${userId}&username=${username}`;

    this.doConnect();
  }

  /** 发送 JSON 消息；未连接时入离线队列，连接建立后冲刷。 */
  public send(data: any) {
    if (!this.sendRaw(JSON.stringify(data))) {
      this.pendingMessages.push(data);
    }
  }

  /** 发送屏幕帧（截图） */
  public sendScreenFrame(imageBase64: string) {
    this.send({ type: 'screen_frame', image_base64: imageBase64, timestamp: Date.now() });
  }

  /** 发送鼠标框选事件 */
  public sendMouseLasso(
    region: { x1: number; y1: number; x2: number; y2: number },
    imageBase64?: string
  ) {
    this.send({ type: 'mouse_lasso', region, image_base64: imageBase64, timestamp: Date.now() });
  }

  /** 发送 ASR 结果 */
  public sendAsrResult(text: string, isFinal: boolean) {
    this.send({ type: 'asr_result', text, is_final: isFinal, timestamp: Date.now() });
  }

  /** 发送显式请求 */
  public sendExplicitRequest(text: string, imageBase64?: string) {
    this.send({ type: 'explicit_request', text, image_base64: imageBase64, timestamp: Date.now() });
  }

  /** 发送心跳 */
  public sendHeartbeat() {
    this.send({ type: 'heartbeat' });
  }

  protected onOpen(): void {
    // Flush pending messages queued while offline
    while (this.pendingMessages.length > 0) {
      const msg = this.pendingMessages.shift();
      if (msg !== undefined) this.send(msg);
    }
  }
}

export const rtaSocket = new RtaSocketService();
