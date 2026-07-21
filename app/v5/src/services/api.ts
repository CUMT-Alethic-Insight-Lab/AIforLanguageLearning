/**
 * @fileoverview 基础 API 客户端模块 (Axios Instance)
 * @description 创建并配置全局唯一的 Axios 实例，用于处理所有 HTTP 请求。
 *              包含统一的请求拦截器（注入 Token）和响应拦截器（错误处理、数据解包）。
 */

import axios from 'axios';
import { getDefaultBackendUrl, normalizeBackendUrl } from './backend-url';

// 后端服务的基础地址（HTTP API）
// 说明：避免从 ConfigService 读取以免循环依赖；改为每次请求从 localStorage 的 app_config 动态读取。
const DEFAULT_BACKEND_URL = getDefaultBackendUrl();

function getConfiguredBackendUrl(): string {
  try {
    const raw = localStorage.getItem('app_config');
    if (!raw) return DEFAULT_BACKEND_URL;
    const cfg = JSON.parse(raw);
    const migrated = normalizeBackendUrl(cfg?.backend?.url);

    if (migrated !== cfg?.backend?.url) {
      try {
        const nextCfg = { ...(cfg || {}), backend: { ...(cfg?.backend || {}), url: migrated } };
        localStorage.setItem('app_config', JSON.stringify(nextCfg));
      } catch {
        // ignore
      }
    }

    return migrated;
  } catch {
    return DEFAULT_BACKEND_URL;
  }
}

/**
 * 创建 Axios 实例
 * 配置了基础 URL、超时时间和默认请求头。
 */
const api = axios.create({
  baseURL: DEFAULT_BACKEND_URL,
  timeout: 10000, // 请求超时时间设置为 10 秒
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * 请求拦截器 (Request Interceptor)
 * 在请求发送前统一处理：
 * 1. 从 LocalStorage 获取认证 Token。
 * 2. 如果 Token 存在，将其添加到 Authorization 请求头中 (Bearer Token)。
 */
api.interceptors.request.use(
  (config) => {
    // 动态注入 baseURL（允许在设置中修改后端地址，无需重启应用）
    config.baseURL = getConfiguredBackendUrl();
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

/**
 * 响应拦截器 (Response Interceptor)
 * 在收到响应后统一处理：
 * 1. 成功响应：直接返回 response.data，简化调用方的代码。
 * 2. 错误响应：统一打印错误日志，并抛出错误供调用方捕获。
 */
api.interceptors.response.use(
  (response) => {
    // 直接返回数据部分，过滤掉 status, headers 等 axios 包装信息
    return response.data;
  },
  (error) => {
    console.error('API 请求发生错误:', error);
    // 这里可以添加统一的错误处理逻辑，如 401 未授权跳转登录页等
    return Promise.reject(error);
  }
);

export default api;
