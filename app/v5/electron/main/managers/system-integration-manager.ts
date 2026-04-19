import { Tray, Menu, nativeImage, globalShortcut, clipboard, app } from 'electron';
import log from 'electron-log';
import fs from 'node:fs';
import { WindowManager } from './window-manager.js';
import { ServiceProbeManager } from './service-probe-manager.js';
import { getRendererFile } from '../utils.js';

export class SystemIntegrationManager {
    private tray: Tray | null = null;
    private windowManager: WindowManager;
    private serviceProbeManager: ServiceProbeManager;

    constructor(windowManager: WindowManager, serviceProbeManager: ServiceProbeManager) {
        this.windowManager = windowManager;
        this.serviceProbeManager = serviceProbeManager;
    }

    public createTray() {
        const iconPath = getRendererFile('icon.png');
        const img = fs.existsSync(iconPath) ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty();
        this.tray = new Tray(img);
        const contextMenu = Menu.buildFromTemplate([
            { label: 'Show Window', click: () => this.windowManager.show() },
            { type: 'separator' },
            { label: 'Reload Services', click: () => this.serviceProbeManager.reloadServices() },
            { type: 'separator' },
            { label: 'Quit', click: () => { 
                this.windowManager.setQuitting(true);
                app.quit(); 
            } }
        ]);
        this.tray.setToolTip('MMLS Services');
        this.tray.setContextMenu(contextMenu);
        this.tray.on('click', () => this.windowManager.show());
    }

    public registerShortcuts() {
        try {
            // 1. 全局查词/查图快捷键（已有）
            const okLookup = globalShortcut.register('CommandOrControl+Shift+L', () => {
                log.info('Global hotkey triggered: vocabulary lookup');
                this._handleClipboardLookup();
            });
            if (!okLookup) log.warn('Hotkey Ctrl+Shift+L not registered');

            // 2. 截图辅助快捷键：读取剪贴板图片并触发 AI 分析
            const okScreenshot = globalShortcut.register('CommandOrControl+Shift+S', () => {
                log.info('Global hotkey triggered: screenshot assist');
                this._handleScreenshotAssist();
            });
            if (!okScreenshot) log.warn('Hotkey Ctrl+Shift+S not registered');

            // 3. 划词/文本辅助快捷键：读取剪贴板文本并触发 AI 分析
            const okTextAssist = globalShortcut.register('CommandOrControl+Shift+C', () => {
                log.info('Global hotkey triggered: clipboard text assist');
                this._handleTextAssist();
            });
            if (!okTextAssist) log.warn('Hotkey Ctrl+Shift+C not registered');

        } catch (e) {
            log.error('registerShortcuts error', e);
        }
    }

    /**
     * 处理查词/查图：读取剪贴板内容（优先文本，其次图片），发送到主窗口触发查询
     */
    private _handleClipboardLookup() {
        const text = clipboard.readText();
        if (text && text.trim()) {
            this.windowManager.show();
            this.windowManager.send('trigger-lookup', { type: 'text', content: text.trim() });
            return;
        }
        
        const image = clipboard.readImage();
        if (!image.isEmpty()) {
            this.windowManager.show();
            const base64 = image.toPNG().toString('base64');
            this.windowManager.send('trigger-lookup', { type: 'image', content: base64 });
            return;
        }
        
        this.windowManager.show();
    }

    /**
     * 截图辅助：读取剪贴板图片，发送到主窗口进行 RTA 分析
     * 
     * 使用方式：用户先用系统截图工具（如 PrintScreen / Snipaste）截图到剪贴板，
     * 然后按 Ctrl+Shift+S，前端自动读取图片并走实时助教分析链路。
     */
    private _handleScreenshotAssist() {
        const image = clipboard.readImage();
        if (image.isEmpty()) {
            log.info('Screenshot assist: no image in clipboard');
            this.windowManager.showSmartOverlay({
                title: '未检测到截图',
                content: '剪贴板中没有图片。请先用系统截图工具截图，再按 Ctrl+Shift+S。',
                priority: 'low',
                hideFooter: true,
            });
            return;
        }

        const base64 = image.toPNG().toString('base64');
        const dataUrl = `data:image/png;base64,${base64}`;
        log.info('Screenshot assist: image captured from clipboard');

        // 发送到主窗口，由渲染进程通过 RTA WebSocket 发送给后端
        this.windowManager.send('system-screenshot', {
            imageBase64: dataUrl,
            timestamp: Date.now(),
            source: 'clipboard_hotkey',
        });
    }

    /**
     * 文本辅助：读取剪贴板文本，发送到主窗口进行 RTA 分析
     * 
     * 使用方式：用户在任何地方选中/复制文本，按 Ctrl+Shift+C，
     * 前端自动读取文本并走实时助教分析链路。
     */
    private _handleTextAssist() {
        const text = clipboard.readText();
        if (!text || !text.trim()) {
            log.info('Text assist: no text in clipboard');
            this.windowManager.showSmartOverlay({
                title: '未检测到文本',
                content: '剪贴板中没有文本。请先复制一段文字，再按 Ctrl+Shift+C。',
                priority: 'low',
                hideFooter: true,
            });
            return;
        }

        log.info('Text assist: text captured from clipboard, length=' + text.trim().length);

        this.windowManager.send('system-text-select', {
            text: text.trim(),
            timestamp: Date.now(),
            source: 'clipboard_hotkey',
        });
    }

    public unregisterShortcuts() {
        globalShortcut.unregisterAll();
    }
}
