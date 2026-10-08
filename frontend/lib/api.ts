// Thin client for the LorvenLax API. Requests go to /api on the same origin
// (Next.js rewrites them to the backend), so the session cookie is first-party.

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)llx_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

function messageFrom(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: string }).message);
  if (status === 0) return "The server could not be reached. Check your connection and try again.";
  return `Request failed (${status})`;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const method = (rest.method || (json !== undefined ? "POST" : "GET")).toUpperCase();
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...rest,
      method,
      credentials: "same-origin",
      headers: {
        ...(json !== undefined ? { "content-type": "application/json" } : {}),
        ...(method !== "GET" ? { "x-csrf-token": csrfToken() } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, messageFrom(null, 0), null);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.status, messageFrom(detail, res.status), detail);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export const fetcher = <T,>(path: string) => api<T>(path);
