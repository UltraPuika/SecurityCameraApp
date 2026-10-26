export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryAfter: number | null;
  readonly detail: Record<string, unknown>;

  constructor(code: string, status: number, retryAfter: number | null = null, detail: Record<string, unknown> = {}) {
    super(code);
    this.code = code;
    this.status = status;
    this.retryAfter = retryAfter;
    this.detail = detail;
  }
}

let csrfToken: string | null = null;

// Empty = same origin. A native wrapper (Capacitor) can set VITE_API_BASE at build time.
const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

export function liveUrl(cameraId: number, quality: "main" | "sub"): string {
  const base = API_BASE ? new URL(API_BASE) : window.location;
  const scheme = base.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${base.host}/api/cameras/${cameraId}/live/${quality}`;
}

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers,
      credentials: "same-origin",
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new ApiError("network", 0);
  }

  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const err =
      typeof data === "object" && data !== null && "error" in data
        ? ((data as { error: Record<string, unknown> }).error ?? {})
        : {};
    const { code, ...detail } = err;
    const ra = res.headers.get("Retry-After");
    throw new ApiError(typeof code === "string" ? code : "unknown", res.status, ra ? Number(ra) : null, detail);
  }
  return data as T;
}
