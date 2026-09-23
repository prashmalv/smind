/**
 * Thin client over the ShopperMind API.
 *
 * The token lives in localStorage rather than a cookie because the API is a separate
 * origin on Azure Container Apps and is called directly from the browser. Every request
 * carries it; a 401 clears it and bounces to login, so an expired session cannot leave
 * the UI showing stale numbers.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "shoppermind.token";
const TENANT_KEY = "shoppermind.tenant";
const USER_KEY = "shoppermind.user";

export type Tenant = {
  id: string; name: string; slug: string; vertical: string;
  currency: string; country: string; timezone: string; plan: string;
  camera_enabled: boolean; voice_enabled: boolean;
};
export type User = {
  id: string; email: string; full_name: string; role: string; job_title: string;
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getTenant(): Tenant | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(TENANT_KEY);
  return raw ? (JSON.parse(raw) as Tenant) : null;
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as User) : null;
}

export function saveSession(token: string, tenant: Tenant, user: User) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(TENANT_KEY, JSON.stringify(tenant));
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(TENANT_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : "Request failed");
    this.status = status;
    this.detail = detail;
  }
}

type Options = {
  method?: string;
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
};

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const { method = "GET", body, auth = true, signal } = opts;
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (res.status === 401 && typeof window !== "undefined") {
    clearSession();
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }

  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const payload = await res.json();
      detail = payload.detail ?? payload;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/* ── formatting ───────────────────────────────────────────────────────────
   Indian digit grouping is the default because the launch market is India, and
   "₹63,88,185" is what a finance team here expects to read — not "₹6,388,185".  */

const LOCALE: Record<string, string> = {
  INR: "en-IN", USD: "en-US", GBP: "en-GB", AED: "en-AE",
};

export function money(value: number | null | undefined, currency = "INR"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(LOCALE[currency] ?? "en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

export function count(value: number | null | undefined, currency = "INR"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(LOCALE[currency] ?? "en-IN").format(Math.round(value));
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value < 90) return `${Math.round(value)}s`;
  return `${(value / 60).toFixed(1)} min`;
}

export function formatMetric(
  value: number | string | null,
  format: string,
  currency = "INR",
): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  switch (format) {
    case "currency": return money(value, currency);
    case "percent": return percent(value);
    case "seconds": return seconds(value);
    default: return count(value, currency);
  }
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  return `${Math.round(hrs / 24)} d ago`;
}
