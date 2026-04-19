import { BrowserWindow, screen, nativeTheme, app } from 'electron';
import path from 'node:path';
import fs from 'node:fs';
import log from 'electron-log';
import { getRendererFile, getPreloadPath } from '../utils.js';

export class WindowManager {
    public mainWindow: BrowserWindow | null = null;
    public overlayWindow: BrowserWindow | null = null;
    public smartOverlayWindow: BrowserWindow | null = null;
    private isQuitting = false;

    constructor() {}

    public createMainWindow(): BrowserWindow {
        this.mainWindow = new BrowserWindow({
            width: 1200,
            height: 780,
            minWidth: 1080,
            minHeight: 700,
            title: 'Multimodal Learning System',
            titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
            backgroundColor: nativeTheme.shouldUseDarkColors ? '#121212' : '#f7f7f9',
            webPreferences: {
                preload: getPreloadPath(),
                nodeIntegration: false,
                contextIsolation: true,
                sandbox: false
            }
        });

        const indexPath = getRendererFile('index.html');
        
        // V5 Migration: Support loading from Vite Dev Server
        if (process.env.VITE_DEV_SERVER_URL) {
            log.info('Loading V5 Dev Server:', process.env.VITE_DEV_SERVER_URL);
            this.mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
        } else if (!fs.existsSync(indexPath)) {
            log.error('Renderer index.html not found at', indexPath);
        } else {
            this.mainWindow.loadFile(indexPath).catch(err => log.error('loadFile error', err));
        }

        this.mainWindow.on('close', (e) => {
            if (!this.isQuitting) {
                e.preventDefault();
                this.mainWindow?.hide();
            }
        });

        this.mainWindow.on('closed', () => {
            this.mainWindow = null;
        });

        return this.mainWindow;
    }

    /**
     * 显示智能悬浮窗（全局透明 overlay）
     * 
     * 支持两种用途：
     * 1. 查词入口悬浮窗（截图/划词后手动触发查词）
     * 2. 智慧助教结果悬浮窗（LLM 在指定位置弹出）
     * 
     * 特性：
     * - 无边框、透明背景、毛玻璃效果
     * - 内容高度根据文本长度自动计算（100px ~ 420px）
     * - 8 秒后自动关闭（可固定）
     * - 支持拖拽移动
     * - 支持自定义位置（x, y），不传则默认屏幕右上角
     */
    public showSmartOverlay(payload: {
        title?: string;
        content?: string;
        priority?: 'high' | 'medium' | 'low';
        actionLabel?: string;
        actionPayload?: any;
        hideFooter?: boolean;
        /** 悬浮窗模式: entry=查词入口, result=结果展示, loading=加载中 */
        mode?: 'entry' | 'result' | 'loading';
        /** 截图预览（entry 模式） */
        imageBase64?: string;
        /** 文本预览（entry 模式） */
        textPreview?: string;
        /** 自定义位置（不传则默认屏幕右上角） */
        x?: number;
        y?: number;
    }) {
        try {
            if (this.smartOverlayWindow && !this.smartOverlayWindow.isDestroyed()) {
                this.smartOverlayWindow.close();
            }

            const display = screen.getPrimaryDisplay();
            const width = 360;
            const initialHeight = payload.mode === 'entry' ? 180 : 160;
            const marginX = 24;
            const marginY = 60;

            // 位置计算：优先使用传入的 x/y，否则默认右上角
            const x = typeof payload.x === 'number'
                ? payload.x
                : display.workArea.x + display.workArea.width - width - marginX;
            const y = typeof payload.y === 'number'
                ? payload.y
                : display.workArea.y + marginY;

            this.smartOverlayWindow = new BrowserWindow({
                width,
                height: initialHeight,
                x,
                y,
                frame: false,
                transparent: true,
                resizable: false,
                alwaysOnTop: true,
                skipTaskbar: true,
                show: false,
                hasShadow: false,
                focusable: false,
                webPreferences: {
                    preload: getPreloadPath(),
                    contextIsolation: true,
                    nodeIntegration: false,
                    sandbox: false,
                }
            });

            this.smartOverlayWindow.setIgnoreMouseEvents(false);
            this.smartOverlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

            const url = new URL('file://' + getRendererFile('overlay.html'));
            url.searchParams.set('payload', encodeURIComponent(JSON.stringify(payload)));

            this.smartOverlayWindow.loadURL(url.toString());
            this.smartOverlayWindow.once('ready-to-show', () => {
                this.smartOverlayWindow?.showInactive();
            });

            this.smartOverlayWindow.on('closed', () => {
                this.smartOverlayWindow = null;
            });
        } catch (e) {
            log.error('showSmartOverlay error', e);
        }
    }

    /**
     * 动态调整智能悬浮窗尺寸（由悬浮窗内脚本调用 IPC 触发）
     */
    public resizeSmartOverlay(width: number, height: number) {
        try {
            if (this.smartOverlayWindow && !this.smartOverlayWindow.isDestroyed()) {
                const [currentX, currentY] = this.smartOverlayWindow.getPosition();
                this.smartOverlayWindow.setBounds({ x: currentX, y: currentY, width, height }, true);
            }
        } catch (e) {
            log.error('resizeSmartOverlay error', e);
        }
    }

    public closeSmartOverlay() {
        try {
            if (this.smartOverlayWindow && !this.smartOverlayWindow.isDestroyed()) {
                this.smartOverlayWindow.close();
                this.smartOverlayWindow = null;
            }
        } catch (e) {
            log.error('closeSmartOverlay error', e);
        }
    }

    public showOverlay(title: string, text: string) {
        try {
            if (this.overlayWindow && !this.overlayWindow.isDestroyed()) {
                this.overlayWindow.close();
            }
            this.overlayWindow = new BrowserWindow({
                width: 420,
                height: 260,
                frame: false,
                transparent: true,
                resizable: false,
                alwaysOnTop: true,
                skipTaskbar: true,
                show: false,
                webPreferences: { contextIsolation: true }
            });

            const display = screen.getPrimaryDisplay();
            const x = display.workArea.x + display.workArea.width - 460;
            const y = display.workArea.y + 40;
            this.overlayWindow.setPosition(x, y);

            const url = new URL('file://' + getRendererFile('overlay.html'));
            url.searchParams.set('title', encodeURIComponent(title));
            url.searchParams.set('text', encodeURIComponent(text));

            this.overlayWindow.loadURL(url.toString());
            this.overlayWindow.once('ready-to-show', () => this.overlayWindow?.show());
            this.overlayWindow.on('blur', () => this.overlayWindow?.close());
        } catch (e) {
            log.error('showOverlay error', e);
        }
    }

    public send(channel: string, data: any) {
        if (this.mainWindow && !this.mainWindow.isDestroyed()) {
            this.mainWindow.webContents.send(channel, data);
        }
    }

    public show() {
        if (this.mainWindow) {
            if (this.mainWindow.isMinimized()) this.mainWindow.restore();
            this.mainWindow.show();
        }
    }

    public setQuitting(val: boolean) {
        this.isQuitting = val;
    }
}
