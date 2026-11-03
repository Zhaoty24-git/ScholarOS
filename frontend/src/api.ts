// Tokens are memory-only. A revision fences work started by an older session.
let accessToken = "";
let revision = 0;
const pending = new Set<AbortController>();
const invalidationListeners = new Set<() => void>();
export function sessionRevision() { return revision; }
export function onSessionInvalidated(listener: () => void) {
  invalidationListeners.add(listener);
  return () => { invalidationListeners.delete(listener); };
}
export function setAccessToken(value: string) {
  revision += 1;
  accessToken = value;
  for (const controller of pending) controller.abort();
  pending.clear();
  if (!value) for (const listener of invalidationListeners) listener();
  return revision;
}
export function authHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}
function requireSession(expected: number) {
  if (!accessToken || revision !== expected) throw new Error("会话已锁定，请重新授权。");
}
export async function apiFetch(path: string, init: RequestInit = {}) {
  const started = revision;
  requireSession(started);
  const headers = new Headers(init.headers);
  headers.delete("Authorization");
  for (const [key, value] of Object.entries(authHeaders())) headers.set(key, value);
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (init.signal?.aborted) controller.abort();
  init.signal?.addEventListener("abort", cancel, { once: true });
  pending.add(controller);
  try {
    const response = await fetch(apiUrl(path), { ...init, headers, signal: controller.signal, credentials: "omit", redirect: "error" });
    requireSession(started);
    if (response.status === 401 || response.status === 503) {
      setAccessToken("");
      throw new Error("授权已失效或后端尚未配置，请重新连接。");
    }
    return response;
  } finally {
    pending.delete(controller);
    init.signal?.removeEventListener("abort", cancel);
  }
}

const API_BASE =
  import.meta.env.VITE_API_BASE
  ?? (import.meta.env.DEV ? "http://127.0.0.1:8000" : window.location.origin);

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}
async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const started = revision;
  const response = await apiFetch(path, init);
  if (!response.ok) throw new Error(`请求失败: ${response.status}`);
  const data = await response.json() as T;
  requireSession(started);
  return data;
}
export function apiGet<T>(path: string): Promise<T> {
  return jsonRequest<T>(path);
}
export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return jsonRequest<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
export function apiUpload<T>(path: string, body: FormData): Promise<T> {
  return jsonRequest<T>(path, { method: "POST", body });
}
export function createSessionClient() {
  const bound = revision;
  return {
    apiGet<T>(path: string) { requireSession(bound); return apiGet<T>(path); },
    apiPost<T>(path: string, body: unknown) { requireSession(bound); return apiPost<T>(path, body); },
    apiUpload<T>(path: string, body: FormData) { requireSession(bound); return apiUpload<T>(path, body); },
  };
}
