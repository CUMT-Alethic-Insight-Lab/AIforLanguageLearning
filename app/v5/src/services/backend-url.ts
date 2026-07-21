const LOCAL_BACKEND_HTTP = 'http://localhost:8012';
const LOCAL_BACKEND_WS_HOST = 'localhost:8012';

function getLocation(): Location | null {
  try {
    return typeof window !== 'undefined' ? window.location : null;
  } catch {
    return null;
  }
}

function isDevFrontendHost(host: string): boolean {
  return /:(5173|5174|8000)\b/.test(host);
}

export function getDefaultBackendUrl(): string {
  const loc = getLocation();
  if (!loc || !loc.host || loc.protocol === 'file:' || isDevFrontendHost(loc.host)) {
    return LOCAL_BACKEND_HTTP;
  }
  if (loc.protocol === 'http:' || loc.protocol === 'https:') {
    return `${loc.protocol}//${loc.host}`;
  }
  return LOCAL_BACKEND_HTTP;
}

export function getDefaultBackendWsHost(): string {
  return normalizeBackendWsHost(getDefaultBackendUrl());
}

export function normalizeBackendUrl(raw?: string | null): string {
  let url = String(raw || '').trim();
  if (!url) return getDefaultBackendUrl();
  if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(url)) {
    url = `http://${url}`;
  }
  url = url.replace(/\/$/, '');

  const migrated = url
    .replace('http://localhost:8011', 'http://localhost:8012')
    .replace('http://127.0.0.1:8011', 'http://127.0.0.1:8012')
    .replace('http://localhost:8000', 'http://localhost:8012')
    .replace('http://127.0.0.1:8000', 'http://127.0.0.1:8012')
    .replace('http://localhost:8005', 'http://localhost:8012')
    .replace('http://127.0.0.1:8005', 'http://127.0.0.1:8012');

  return migrated;
}

export function normalizeBackendWsHost(raw?: string | null): string {
  let host = String(raw || '').trim();
  if (!host) return LOCAL_BACKEND_WS_HOST;
  host = host.replace(/^https?:\/\//, '').replace(/^wss?:\/\//, '').replace(/\/$/, '');
  host = host
    .replace('localhost:8011', 'localhost:8012')
    .replace('127.0.0.1:8011', '127.0.0.1:8012')
    .replace('localhost:8000', 'localhost:8012')
    .replace('127.0.0.1:8000', '127.0.0.1:8012')
    .replace('localhost:8005', 'localhost:8012')
    .replace('127.0.0.1:8005', '127.0.0.1:8012');

  const loc = getLocation();
  if (loc?.host && host === loc.host && isDevFrontendHost(loc.host)) {
    return LOCAL_BACKEND_WS_HOST;
  }
  return host;
}

export function buildWsUrl(rawBackend?: string | null, pathAndQuery: string = '/ws/v1'): string {
  const raw = String(rawBackend || '').trim();
  let scheme = getLocation()?.protocol === 'https:' ? 'wss' : 'ws';
  if (/^wss:\/\//.test(raw) || /^https:\/\//.test(raw)) scheme = 'wss';
  if (/^ws:\/\//.test(raw) || /^http:\/\//.test(raw)) scheme = 'ws';

  const host = normalizeBackendWsHost(raw || getDefaultBackendWsHost());
  const path = pathAndQuery.startsWith('/') ? pathAndQuery : `/${pathAndQuery}`;
  return `${scheme}://${host}${path}`;
}
