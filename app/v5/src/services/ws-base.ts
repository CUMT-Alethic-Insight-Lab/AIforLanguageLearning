/**
 * @fileoverview WebSocket 连接基类
 * @description 承载两个 WS 服务（voice/rta）共用的能力：
 *              指数退避重连、消息订阅分发、连接状态、JSON 消息解析。
 *              子类通过钩子定制：onSocketCreated / onOpen / onMessageData /
 *              prepareReconnect，以及 send 的离线策略。
 */

import { ref } from 'vue';

export type MessageHandler = (msg: any) => void;

export abstract class BaseWsService {
  protected ws: WebSocket | null = null;
  protected url: string = '';

  protected reconnectAttempts = 0;
  protected maxReconnectAttempts = 5;
  private messageHandlers: MessageHandler[] = [];

  public isConnected = ref(false);
  public isConnecting = ref(false);

  protected constructor(protected readonly tag: string = 'WS') {}

  /** 连接已建立（含重连成功）。子类可在此做协议握手或冲刷离线队列。 */
  protected onOpen(): void {}

  /** JSON 解析成功后的钩子，在分发给订阅者之前调用。 */
  protected onMessageData(_data: any): void {}

  /** 重连前钩子：子类可在此刷新 URL（如携带 last_seq）。 */
  protected prepareReconnect(): void {}

  /** WebSocket 对象创建后的钩子（如设置 binaryType）。 */
  protected onSocketCreated(_ws: WebSocket): void {}

  protected doConnect() {
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    this.isConnecting.value = true;
    console.log(`[${this.tag}] Connecting:`, this.url);
    this.ws = new WebSocket(this.url);
    this.onSocketCreated(this.ws);

    this.ws.onopen = () => {
      console.log(`[${this.tag}] Connected`);
      this.isConnected.value = true;
      this.isConnecting.value = false;
      this.reconnectAttempts = 0;
      this.onOpen();
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.onMessageData(data);
        this.notifyHandlers(data);
      } catch (e) {
        console.error(`[${this.tag}] Message parse error:`, e);
      }
    };

    this.ws.onclose = () => {
      console.log(`[${this.tag}] Disconnected`);
      this.isConnected.value = false;
      this.isConnecting.value = false;
      this.handleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error(`[${this.tag}] Error:`, err);
      this.isConnected.value = false;
      this.isConnecting.value = false;
    };
  }

  /** 底层发送：仅在连接打开时发送，返回是否成功。 */
  protected sendRaw(data: string | ArrayBuffer | Int16Array | Uint8Array): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(data as any);
      return true;
    }
    return false;
  }

  /** 发送 JSON 消息（默认无离线队列，子类可覆写）。 */
  public send(data: any) {
    this.sendRaw(JSON.stringify(data));
  }

  /** 注册消息监听器，返回取消订阅函数。 */
  public onMessage(handler: MessageHandler) {
    this.messageHandlers.push(handler);
    return () => {
      this.messageHandlers = this.messageHandlers.filter((h) => h !== handler);
    };
  }

  private notifyHandlers(msg: any) {
    this.messageHandlers.forEach((h) => h(msg));
  }

  /** 指数退避重连：min(1000 * 2^n, 30000)ms，最多 5 次。 */
  private handleReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
      console.log(`[${this.tag}] Reconnecting in ${delay}ms...`);
      setTimeout(() => {
        this.reconnectAttempts++;
        this.prepareReconnect();
        this.doConnect();
      }, delay);
    }
  }

  /** 主动断开连接（不触发重连的静默断开由子类自行清理回调后调用）。 */
  public disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
