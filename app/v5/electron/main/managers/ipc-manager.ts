import { ipcMain, shell, app, clipboard } from 'electron';
import Store from 'electron-store';
import log from 'electron-log';
import fs from 'node:fs';
import { WindowManager } from './window-manager.js';
import { ServiceProbeManager } from './service-probe-manager.js';
import { Config, SKey } from '../types.js';
import { AsrManager } from './asr-manager.js';

function normalizeBackendConfig(input: { url?: string; wsUrl?: string }) {
    const rawUrl = String(input?.url || '').trim();
    let url = rawUrl;
    if (url && !/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(url)) {
        url = `http://${url}`;
    }
    url = url.replace(/\/$/, '');
    url = url.replace('http://localhost:8011', 'http://localhost:8012');
    url = url.replace('http://127.0.0.1:8011', 'http://127.0.0.1:8012');
    url = url.replace('http://localhost:8000', 'http://localhost:8012');
    url = url.replace('http://127.0.0.1:8000', 'http://127.0.0.1:8012');

    const rawWs = String(input?.wsUrl || '').trim();
    let wsUrl = rawWs.replace(/^wss?:\/\//, '');
    wsUrl = wsUrl.replace('localhost:8011', 'localhost:8012');
    wsUrl = wsUrl.replace('127.0.0.1:8011', '127.0.0.1:8012');
    wsUrl = wsUrl.replace('localhost:8000', 'localhost:8012');
    wsUrl = wsUrl.replace('127.0.0.1:8000', '127.0.0.1:8012');

    return {
        url: url || 'http://localhost:8012',
        wsUrl: wsUrl || 'localhost:8012',
    };
}

export class IpcManager {
    private store: Store<Config>;
    private windowManager: WindowManager;
    private serviceProbeManager: ServiceProbeManager;
    private asrManager: AsrManager;

    constructor(store: Store<Config>, windowManager: WindowManager, serviceProbeManager: ServiceProbeManager) {
        this.store = store;
        this.windowManager = windowManager;
        this.serviceProbeManager = serviceProbeManager;
        this.asrManager = new AsrManager();
        this.asrManager.registerIpcHandlers();
    }

    public registerHandlers() {
        ipcMain.handle('config:get', () => {
            const ports = this.store.get('ports') ?? { lmstudio: null, whisper: null, surya: null, cosy: null, app: 0 };
            const legacyTheme = this.store.get('theme') ?? 'system';
            const legacyBackendUrl = this.store.get('backendUrl') ?? 'localhost:8012';

            const general = this.store.get('general') ?? { theme: legacyTheme, language: 'zh-CN', autoUpdate: true };
            const audio = this.store.get('audio') ?? { inputDevice: 'default', outputDevice: 'default', volume: 80 };
            const ai = this.store.get('ai') ?? { model: 'local-model', temperature: 0.7, voice: 'alloy' };
            const backendRaw = this.store.get('backend') ?? { url: 'http://localhost:8012', wsUrl: legacyBackendUrl };
            const backend = normalizeBackendConfig(backendRaw);

            this.store.set('backend', backend);
            this.store.set('backendUrl', backend.wsUrl);

            // 返回给渲染进程的对象尽量对齐 AppConfig 结构；保留 ports 以兼容可能的使用方。
            return {
                ports,
                general,
                audio,
                ai,
                backend
            };
        });

        ipcMain.handle('config:set', (_e, patch: Partial<Config>) => {
            if (patch?.ports) {
                const current = this.store.get('ports') ?? { lmstudio: null, whisper: null, surya: null, cosy: null, app: 0 };
                this.store.set('ports', { ...current, ...patch.ports });
            }

            // 兼容旧字段
            if ((patch as any)?.theme) {
                this.store.set('theme', (patch as any).theme);
            }
            if ((patch as any)?.backendUrl) {
                this.store.set('backendUrl', (patch as any).backendUrl);
            }

            // 新字段（AppConfig-ish）
            if ((patch as any)?.general) {
                const current = this.store.get('general') ?? { theme: 'system', language: 'zh-CN', autoUpdate: true };
                this.store.set('general', { ...current, ...(patch as any).general });
                // 同步 legacy theme
                if ((patch as any).general?.theme) {
                    this.store.set('theme', (patch as any).general.theme);
                }
            }
            if ((patch as any)?.audio) {
                const current = this.store.get('audio') ?? { inputDevice: 'default', outputDevice: 'default', volume: 80 };
                this.store.set('audio', { ...current, ...(patch as any).audio });
            }
            if ((patch as any)?.ai) {
                const current = this.store.get('ai') ?? { model: 'local-model', temperature: 0.7, voice: 'alloy' };
                this.store.set('ai', { ...current, ...(patch as any).ai });
            }
            if ((patch as any)?.backend) {
                const current = this.store.get('backend') ?? { url: 'http://localhost:8012', wsUrl: 'localhost:8012' };
                const merged = { ...current, ...(patch as any).backend };
                const normalized = normalizeBackendConfig(merged);
                this.store.set('backend', normalized);
                // 同步 legacy backendUrl
                this.store.set('backendUrl', normalized.wsUrl);
            }

            return {
                ports: this.store.get('ports'),
                general: this.store.get('general'),
                audio: this.store.get('audio'),
                ai: this.store.get('ai'),
                backend: this.store.get('backend')
            };
        });

        ipcMain.handle('service:start', (_e, key: SKey) => {
            this.serviceProbeManager.updateState(key, { status: 'starting', message: 'Starting...' });
            return true;
        });

        ipcMain.handle('service:stop', (_e, key: SKey) => {
            this.serviceProbeManager.updateState(key, { status: 'stopped', message: 'Stopped by user' });
            return true;
        });

        ipcMain.handle('service:probe', async () => {
            await this.serviceProbeManager.probeOnce();
            return true;
        });

        ipcMain.handle('config:open-path', async () => {
            try {
                const cfgPath = this.store.path;
                if (cfgPath && fs.existsSync(cfgPath)) {
                    shell.showItemInFolder(cfgPath);
                    return { ok: true, path: cfgPath };
                }
                const dir = app.getPath('userData');
                await shell.openPath(dir);
                return { ok: true, path: dir };
            } catch (e) {
                log.error('config:open-path error', e);
                return { ok: false, error: String(e) };
            }
        });

        ipcMain.handle('service:state', async () => {
            return this.serviceProbeManager.getState();
        });

        ipcMain.handle('overlay:show', async (_e, payload: { title: string; text: string }) => {
            try {
                this.windowManager.showOverlay(String(payload?.title || '提示'), String(payload?.text || ''));
                return true;
            } catch (e) {
                log.error('overlay:show error', e);
                return false;
            }
        });

        // ── 智能悬浮窗 IPC ──

        ipcMain.handle('smart-overlay:show', async (_e, payload: any) => {
            try {
                this.windowManager.showSmartOverlay(payload);
                return true;
            } catch (e) {
                log.error('smart-overlay:show error', e);
                return false;
            }
        });

        ipcMain.handle('smart-overlay:close', async () => {
            try {
                this.windowManager.closeSmartOverlay();
                return true;
            } catch (e) {
                log.error('smart-overlay:close error', e);
                return false;
            }
        });

        ipcMain.handle('smart-overlay:resize', async (_e, bounds: { width: number; height: number }) => {
            try {
                this.windowManager.resizeSmartOverlay(bounds.width, bounds.height);
                return true;
            } catch (e) {
                log.error('smart-overlay:resize error', e);
                return false;
            }
        });

        ipcMain.on('smart-overlay:action', (_e, data: any) => {
            // Forward overlay action to main window
            this.windowManager.send('smart-overlay-action', data);
        });

        // ── 剪贴板 IPC ──

        ipcMain.handle('clipboard:read-text', () => {
            return clipboard.readText();
        });

        ipcMain.handle('clipboard:read-image', () => {
            const image = clipboard.readImage();
            if (image.isEmpty()) return null;
            return `data:image/png;base64,${image.toPNG().toString('base64')}`;
        });
    }
}
