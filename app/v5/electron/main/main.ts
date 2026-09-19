import { app, BrowserWindow } from 'electron';
import path from 'node:path';
import fs from 'node:fs';
import log from 'electron-log';
import Store from 'electron-store';
import { WindowManager } from './managers/window-manager.js';
import { ServiceProbeManager } from './managers/service-probe-manager.js';
import { IpcManager } from './managers/ipc-manager.js';
import { SystemIntegrationManager } from './managers/system-integration-manager.js';
import { Config } from './types.js';

// Log setup
log.initialize({ preload: true });
log.transports.file.level = 'info';
log.transports.file.resolvePathFn = (_variables) => {
    const logDir = path.join(app.getPath('userData'), 'logs');
    if (!fs.existsSync(logDir)) fs.mkdirSync(logDir, { recursive: true });
    return path.join(logDir, 'app.log');
};
log.info('App starting...');

// Store setup
const store = new Store<Config>({
    name: 'config',
    defaults: {
        ports: { lmstudio: null, whisper: null, surya: null, cosy: null, app: 0 },
        theme: 'system',
        backendUrl: 'localhost:8012',
        backend: {
            url: 'http://localhost:8012',
            wsUrl: 'localhost:8012'
        },
        general: { theme: 'system', language: 'zh-CN', autoUpdate: true },
        audio: { inputDevice: 'default', outputDevice: 'default', volume: 80 },
        ai: { model: 'local-model', temperature: 0.7, voice: 'alloy' }
    }
});

// Managers
const windowManager = new WindowManager();
const serviceProbeManager = new ServiceProbeManager(store, windowManager);
const ipcManager = new IpcManager(store, windowManager, serviceProbeManager);
const systemIntegrationManager = new SystemIntegrationManager(windowManager, serviceProbeManager);

// Register IPC handlers
ipcManager.registerHandlers();

app.on('ready', () => {
    const mainWindow = windowManager.createMainWindow();
    systemIntegrationManager.createTray();
    systemIntegrationManager.registerShortcuts();
    serviceProbeManager.initializeServicesVisual();
    serviceProbeManager.startProbing();

    // Permission handler
    if (mainWindow) {
        mainWindow.webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
            if (permission === 'media') {
                callback(true);
            } else {
                callback(false);
            }
        });
    }
});

app.on('window-all-closed', () => { /* Keep running */ });

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) windowManager.createMainWindow();
});

app.on('before-quit', async () => {
    windowManager.setQuitting(true);
    serviceProbeManager.stopProbing();
    systemIntegrationManager.unregisterShortcuts();
    log.info('App quitting');
});
