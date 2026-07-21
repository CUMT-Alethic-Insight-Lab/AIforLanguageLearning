/**
 * @fileoverview 认证服务模块 (Authentication Service)
 * @description 封装用户登录、自动登录保活等身份验证相关的业务逻辑。
 */

import api from './api';

export interface AuthUser {
  id: number;
  username: string;
  role: 'student' | 'teacher' | 'admin';
}

interface AuthResponse {
  success: boolean;
  data?: {
    accessToken: string;
    refreshToken: string;
    user: AuthUser;
  };
}

const VALID_ROLES = new Set<AuthUser['role']>(['student', 'teacher', 'admin']);

function isTokenType(token: string, expectedType: 'access' | 'refresh'): boolean {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return false;
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=');
    const bytes = Uint8Array.from(atob(padded), char => char.charCodeAt(0));
    const payload = JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>;
    return (
      payload.token_type === expectedType &&
      typeof payload.exp === 'number' &&
      payload.exp > Date.now() / 1000
    );
  } catch {
    return false;
  }
}

function isAuthUser(value: unknown): value is AuthUser {
  if (!value || typeof value !== 'object') return false;
  const user = value as Record<string, unknown>;
  return (
    typeof user.id === 'number' &&
    Number.isInteger(user.id) &&
    user.id > 0 &&
    typeof user.username === 'string' &&
    user.username.length > 0 &&
    typeof user.role === 'string' &&
    VALID_ROLES.has(user.role as AuthUser['role'])
  );
}

function clearSession(): void {
  localStorage.removeItem('auth_token');
  localStorage.removeItem('auth_refresh_token');
  localStorage.removeItem('auth_user');
}

function persistSession(response: AuthResponse): boolean {
  const session = response.data;
  if (
    !response.success ||
    !session ||
    typeof session.accessToken !== 'string' ||
    !isTokenType(session.accessToken, 'access') ||
    typeof session.refreshToken !== 'string' ||
    !isTokenType(session.refreshToken, 'refresh') ||
    !isAuthUser(session.user)
  ) {
    return false;
  }

  localStorage.setItem('auth_token', session.accessToken);
  localStorage.setItem('auth_refresh_token', session.refreshToken);
  localStorage.setItem('auth_user', JSON.stringify(session.user));
  return true;
}

export const AuthService = {
  /**
   * 用户登录
   * 
   * 向后端发送用户名和密码进行验证。
   * 验证成功后，将 Access Token 和用户信息保存到 LocalStorage。
   * 
   * @param {string} username - 用户名
   * @param {string} password - 密码
   * @returns {Promise<boolean>} 登录成功返回 true，失败返回 false
   */
  async login(username: string, password: string): Promise<boolean> {
    try {
      const response = await api.post('/api/auth/login', { username, password });
      return persistSession(response as unknown as AuthResponse);
    } catch {
      return false;
    }
  },

  async register(username: string, email: string, password: string): Promise<boolean> {
    try {
      const response = await api.post('/api/auth/register', { username, email, password });
      return persistSession(response as unknown as AuthResponse);
    } catch {
      return false;
    }
  },

  async refreshSession(): Promise<boolean> {
    const refreshToken = localStorage.getItem('auth_refresh_token');
    if (!refreshToken) {
      clearSession();
      return false;
    }

    try {
      const response = await api.post('/api/auth/refresh', { refreshToken });
      if (persistSession(response as unknown as AuthResponse)) return true;
    } catch {
      // The caller only needs the session outcome; request details may contain credentials.
    }
    clearSession();
    return false;
  },

  logout(): void {
    clearSession();
  },

  getCurrentUser(): AuthUser | null {
    try {
      const raw = localStorage.getItem('auth_user');
      const user = raw ? JSON.parse(raw) as unknown : null;
      if (isAuthUser(user)) return user;
    } catch {
      // Invalid local state is cleared below.
    }
    clearSession();
    return null;
  },

  hasToken(): boolean {
    const token = localStorage.getItem('auth_token');
    if (!token || !isTokenType(token, 'access')) {
      clearSession();
      return false;
    }
    return this.getCurrentUser() !== null;
  },

  /**
   * 确保用户已登录 (自动登录/保活)
   * 
   * 检查本地是否存在 Token。
   * 如果不存在，返回 false，由路由守卫跳转登录页。
   * 
   * @returns {Promise<boolean>} 如果最终处于登录状态返回 true
   */
  async ensureLogin(): Promise<boolean> {
    return this.hasToken();
  }
};
