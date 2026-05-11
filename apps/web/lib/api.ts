// Typed fetch client + SWR fetcher. v0 reads tenant from a localStorage value
// (default 'default' to match the bootstrap seed). Real auth swaps this out.

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TENANT_STORAGE_KEY = "meaninggrid.tenant";
const DEFAULT_TENANT = "default";

export function getTenant(): string {
  if (typeof window === "undefined") return DEFAULT_TENANT;
  return window.localStorage.getItem(TENANT_STORAGE_KEY) ?? DEFAULT_TENANT;
}

export function setTenant(tenant: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TENANT_STORAGE_KEY, tenant);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Tenant-Id", getTenant());
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const fetcher = <T,>(path: string) => request<T>(path);

export const api = {
  health: () => request<{ status: string }>("/healthz"),

  ingestJson: (body: {
    source: string;
    type: string;
    subject: string;
    data?: unknown;
  }) =>
    request<import("./types").IngestResponse>("/api/v1/ingest", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  ingestFile: (file: File, source = "file", subject?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("source", source);
    if (subject) fd.append("subject", subject);
    return request<import("./types").IngestResponse>("/api/v1/ingest/file", {
      method: "POST",
      body: fd,
    });
  },
};
