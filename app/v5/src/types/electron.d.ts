export interface IElectronAPI {
  // Event Subscriptions
  onServiceUpdate: (cb: (payload: any) => void) => () => void;
  onVocabularyHotkey: (cb: () => void) => () => void;
  onTriggerLookup: (cb: (data: { type: 'text' | 'image', content: string }) => void) => () => void;

  // 系统级截图/划词事件
  onSystemScreenshot: (cb: (data: { imageBase64: string; timestamp: number; source: string }) => void) => () => void;
  onSystemTextSelect: (cb: (data: { text: string; timestamp: number; source: string }) => void) => () => void;

  // 悬浮窗操作事件
  onSmartOverlayAction: (cb: (data: any) => void) => () => void;

  // Softbus Events
  onSoftbusConnected: (cb: () => void) => () => void;
  onSoftbusDisconnected: (cb: () => void) => () => void;
  onSoftbusError: (cb: (err: any) => void) => () => void;
  onSoftbusMessage: (cb: (msg: any) => void) => () => void;
  onSoftbusStreamData: (cb: (data: any) => void) => () => void;
  onSoftbusStreamEnd: (cb: (info: any) => void) => () => void;

  // Config Management
  getConfig: () => Promise<any>;
  setConfig: (patch: any) => Promise<void>;
  openConfigPath: () => Promise<void>;

  // Service Control
  startService: (key: string) => Promise<void>;
  stopService: (key: string) => Promise<void>;
  probeServices: () => Promise<any>;
  getServiceState: () => Promise<any>;

  // Legacy Overlay
  overlayShow: (title: string, text: string) => Promise<void>;

  // Smart Overlay
  smartOverlayShow: (payload: any) => Promise<void>;
  smartOverlayClose: () => Promise<void>;
  smartOverlayResize: (bounds: { width: number; height: number }) => Promise<void>;

  // Clipboard
  clipboardReadText: () => Promise<string>;
  clipboardReadImage: () => Promise<string | null>;

  // Softbus API
  softbus: {
    status: () => Promise<any>;
    publish: (topic: string, data: any, contentType?: string) => Promise<void>;
    subscribe: (topic: string) => Promise<void>;
    unsubscribe: (topic: string) => Promise<void>;
    rpc: (method: string, params?: any, timeout?: number) => Promise<any>;
    streamOpen: (streamId: string, topic: string) => Promise<void>;
    streamSend: (streamId: string, data: any) => Promise<void>;
    streamEnd: (streamId: string) => Promise<void>;
    disconnect: () => Promise<void>;
  };

  // Orchestrator API
  orchestrator: {
    status: () => Promise<any>;
    getServices: () => Promise<any>;
    getMetrics: () => Promise<any>;
    executePipeline: (name: string, data: any) => Promise<any>;
    send: (topic: string, data: any, contentType?: string) => Promise<void>;
  };
}

declare global {
  interface Window {
    api: IElectronAPI;
  }
}
