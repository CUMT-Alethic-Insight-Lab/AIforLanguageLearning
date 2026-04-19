/**
 * @fileoverview 实时助教 WebSocket 服务 (RTA Socket)
 * @description 封装与后端 /api/v1/realtime-assistant/ws 的 WebSocket 连接。
 *              支持自动重连、消息分发、屏幕帧/ASR/显式请求等事件发送。
 */

import { ref } from 'vue';

type MessageHandler = (msg: any) => void;

export interface RtaConnectOptions {
  backendWsUrl: string; // e.g. "localhost:8012"
  userId: number;
  username?: string;
}

class RtaSocketService {
  private ws: WebSocket | null = null;
  private url: string = '';

  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private messageHandlers: MessageHandler[] = [];
  private pendingMessages: any[] = [];

  public isConnected = ref(false);
  public isConnecting = ref(false);

  public connect(options: RtaConnectOptions) {
    const host = options.backendWsUrl.replace(/^wss?:\/\//, '').replace(/\/$/, '');
    const userId = encodeURIComponent(String(options.userId));
    const username = encodeURIComponent(options.username || `user_${options.userId}`);
    this.url = `ws://${host}/api/v1/realtime-assistant/ws?user_id=${userId}&username=${username}`;

    this.doConnect();
  }

  private doConnect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;

    this.isConnecting.value = true;
    console.log('[RTA] Connecting:', this.url);
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log('[RTA] Connected');
      this.isConnected.value = true;
      this.isConnecting.value = false;
      this.reconnectAttempts = 0;
      // Flush pending messages
      while (this.pendingMessages.length > 0) {
        const msg = this.pendingMessages.shift();
        this.send(msg);
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.notifyHandlers(data);
      } catch (e) {
        console.error('[RTA] Message parse error:', e);
      }
    };

    this.ws.onclose = () => {
      console.log('[RTA] Disconnected');
      this.isConnected.value = false;
      this.isConnecting.value = false;
      this.handleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error('[RTA] Error:', err);
      this.isConnected.value = false;
      this.isConnecting.value = false;
    };
  }

  public send(data: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    } else {
      this.pendingMessages.push(data);
    }
  }

  /** 发送屏幕帧（截图） */
  public sendScreenFrame(imageBase64: string) {
    this.send({ type: 'screen_frame', image_base64: imageBase64, timestamp: Date.now() });
  }

  /** 发送鼠标框选事件 */
  public sendMouseLasso(region: { x1: number; y1: number; x2: number; y2: number }, imageBase64?: string) {
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

  public onMessage(handler: MessageHandler) {
    this.messageHandlers.push(handler);
    return () => {
      this.messageHandlers = this.messageHandlers.filter(h => h !== handler);
    };
  }

  private notifyHandlers(msg: any) {
    this.messageHandlers.forEach(h => h(msg));
  }

  private handleReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
      console.log(`[RTA] Reconnecting in ${delay}ms...`);
      setTimeout(() => {
        this.reconnectAttempts++;
        this.doConnect();
      }, delay);
    }
  }

  public disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

export const rtaSocket = new RtaSocketService();
