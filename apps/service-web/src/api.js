const KEY = 'tk-service-session';
export const API_BASE = (import.meta.env.VITE_API_BASE || '/api/v1').replace(/\/$/, '');
export function session() {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || 'null');
  } catch {
    return null;
  }
}
export function saveSession(value) {
  value ? sessionStorage.setItem(KEY, JSON.stringify(value)) : sessionStorage.removeItem(KEY);
}
export class ApiError extends Error {
  constructor(message, status, code, fields) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}
export function query(values) {
  const q = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v !== '' && v !== null && v !== undefined) q.set(k, String(v));
  });
  return q.toString();
}
export async function request(
  path,
  { method = 'GET', body, timeout = 30000, signal, raw = false } = {},
) {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener('abort', cancel, { once: true });
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const token = session()?.token;
    const headers = { Accept: raw ? 'image/*' : 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined && !(body instanceof FormData))
      headers['Content-Type'] = 'application/json';
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
      signal: controller.signal,
      cache: 'no-store',
    });
    if (response.status === 401) {
      saveSession(null);
      window.dispatchEvent(new Event('tk:unauthorized'));
    }
    if (!response.ok) {
      let err = {};
      try {
        err = await response.json();
      } catch {}
      throw new ApiError(
        err.message || `请求失败（${response.status}）`,
        response.status,
        err.code,
        err.fieldErrors,
      );
    }
    if (raw) return response.blob();
    return response.status === 204 ? {} : await response.json();
  } catch (error) {
    if (error.name === 'AbortError')
      throw new ApiError('请求已取消或超时，请先刷新查看处理结果。', 0, 'TIMEOUT');
    if (error instanceof ApiError) throw error;
    throw new ApiError('网络连接失败，请检查服务器连接。', 0, 'NETWORK_ERROR');
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
  }
}
export const get = (path, options) => request(path, options);
export const post = (path, body, options = {}) =>
  request(path, { ...options, method: 'POST', body });
export const put = (path, body) => request(path, { method: 'PUT', body });
export const patch = (path, body) => request(path, { method: 'PATCH', body });
export const uid = () =>
  globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
