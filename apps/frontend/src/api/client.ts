const configuredApiBase = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

function resolveApiBase() {
  if (typeof window === "undefined") {
    return configuredApiBase;
  }
  const host = window.location.hostname;
  const isLocalHost = host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0";
  const configuredIsLocal = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$/i.test(configuredApiBase);
  if (configuredIsLocal && !isLocalHost) {
    return "";
  }
  return configuredApiBase;
}

const API_BASE = resolveApiBase();

export const apiBase = API_BASE;

export function storageUrl(path?: string | null) {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  if (path.startsWith("/")) return `${API_BASE}${path}`;
  return "";
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem("bella_admin_token");
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("ngrok-skip-browser-warning", "true");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Ошибка запроса" }));
    throw new Error(error.detail || "Ошибка запроса");
  }
  return response.json() as Promise<T>;
}
