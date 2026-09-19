/**
 * @fileoverview Electron 预加载脚本 (Preload Script)
 * @description
 * 该脚本在渲染进程加载之前运行，用于安全地将主进程的功能暴露给渲染进程。
 * 通过 `contextBridge` 暴露 `window.api` 对象，实现隔离环境下的 IPC 通信。
 * 
 * 主要暴露的 API 包括：
 * 1. 事件订阅 (Event Subscriptions)：`
 *    - 服务状态更新 (onServiceUpdate)
 *    - 快捷键触发 (onVocabularyHotkey, onTriggerLookup)
 *    - 系统截图/划词事件 (onSystemScreenshot, onSystemTextSelect)
 *    - 悬浮窗操作事件 (onSmartOverlayAction)
 * 
 * 2. 配置管理 (Configuration Management)：
 *    - 获取/设置配置 (getConfig, setConfig)
 *    - 打开配置文件路径 (openConfigPath)
 * 
 * 3. 服务控制 (Service Control)：
 *    - 启动/停止服务 (startService, stopService)
 *    - 探测服务状态 (probeServices, getServiceState)
 * 
 * 4. 剪贴板与悬浮窗 (Clipboard & Overlay)：
 *    - 读取剪贴板 (clipboardReadText, clipboardReadImage)
 *    - 显示智能悬浮窗 (smartOverlayShow, smartOverlayClose)
 *    - 悬浮窗内容更新/关闭回调 (onOverlayUpdate, overlayResize, overlayClose, overlayAction)
 * 
 * @author AI for Foreign Language Learning Team
 * @lastModified 2025-01
 */
import { contextBridge, ipcRenderer } from 'electron';
import type { AsrOptions } from './managers/asr-manager.js';

// 预加载脚本：用 contextBridge 安全地把主进程能力暴露给渲染器
// 暴露的 API 需谨慎设计，只暴露必要的异步方法与事件订阅
contextBridge.exposeInMainWorld('api', {
 // 事件订阅
 onServiceUpdate: (cb: (evt: any) => void) => {
  const listener = (_e: any, payload: any) => cb(payload);
  ipcRenderer.on('service:update', listener);
  return () => ipcRenderer.removeListener('service:update', listener);
 },
 onVocabularyHotkey: (cb: () => void) => {
  const listener = () => cb();
  ipcRenderer.on('hotkey:vocabulary', listener);
  return () => ipcRenderer.removeListener('hotkey:vocabulary', listener);
 },
 onTriggerLookup: (cb: (data: { type: 'text' | 'image', content: string }) => void) => {
  const listener = (_e: any, data: any) => cb(data);
  ipcRenderer.on('trigger-lookup', listener);
  return () => ipcRenderer.removeListener('trigger-lookup', listener);
 },

 // 系统级截图/划词事件（由全局快捷键触发）
 onSystemScreenshot: (cb: (data: { imageBase64: string; timestamp: number; source: string }) => void) => {
  const listener = (_e: any, data: any) => cb(data);
  ipcRenderer.on('system-screenshot', listener);
  return () => ipcRenderer.removeListener('system-screenshot', listener);
 },
 onSystemTextSelect: (cb: (data: { text: string; timestamp: number; source: string }) => void) => {
  const listener = (_e: any, data: any) => cb(data);
  ipcRenderer.on('system-text-select', listener);
  return () => ipcRenderer.removeListener('system-text-select', listener);
 },

 // 悬浮窗操作事件（overlay 中的按钮点击会转发到主窗口）
 onSmartOverlayAction: (cb: (data: any) => void) => {
  const listener = (_e: any, data: any) => cb(data);
  ipcRenderer.on('smart-overlay-action', listener);
  return () => ipcRenderer.removeListener('smart-overlay-action', listener);
 },
 
 // 配置管理
 getConfig: () => ipcRenderer.invoke('config:get'),
 setConfig: (patch: any) => ipcRenderer.invoke('config:set', patch),
 openConfigPath: () => ipcRenderer.invoke('config:open-path'),
 
 // 服务控制与状态查询
 startService: (key: string) => ipcRenderer.invoke('service:start', key),
 stopService: (key: string) => ipcRenderer.invoke('service:stop', key),
 probeServices: () => ipcRenderer.invoke('service:probe'),
 getServiceState: () => ipcRenderer.invoke('service:state'),
 
 // 悬浮层控制（无需 HTTP）
 overlayShow: (title: string, text: string) => ipcRenderer.invoke('overlay:show', { title, text }),
 
 // ── 智能悬浮窗 API ──
 smartOverlayShow: (payload: any) => ipcRenderer.invoke('smart-overlay:show', payload),
 smartOverlayClose: () => ipcRenderer.invoke('smart-overlay:close'),
 smartOverlayResize: (bounds: { width: number; height: number }) => ipcRenderer.invoke('smart-overlay:resize', bounds),
 
 // 悬浮窗内部页面使用的 API（通过同一 preload 加载）
 onOverlayUpdate: (cb: (data: any) => void) => {
  const listener = (_e: any, data: any) => cb(data);
  ipcRenderer.on('overlay:update', listener);
  return () => ipcRenderer.removeListener('overlay:update', listener);
 },
 overlayResize: (bounds: { width: number; height: number }) => ipcRenderer.send('smart-overlay:resize', bounds),
 overlayClose: () => ipcRenderer.send('smart-overlay:close'),
 overlayAction: (data: any) => ipcRenderer.send('smart-overlay:action', data),

 // ── 剪贴板 API ──
 clipboardReadText: () => ipcRenderer.invoke('clipboard:read-text'),
 clipboardReadImage: () => ipcRenderer.invoke('clipboard:read-image'),
 
 // ASR API（桌面端本地辅助链路，当前主语音链路以后台 SeamlessM4T 为准）
 asr: {
  transcribeFromBase64: (base64Wav: string, options?: AsrOptions) =>
    ipcRenderer.invoke('asr:transcribe-from-base64', base64Wav, options),
  status: () => ipcRenderer.invoke('asr:status'),
  stopServer: () => ipcRenderer.invoke('asr:stop-server'),
 }
});

declare global { interface Window { api: any } }
