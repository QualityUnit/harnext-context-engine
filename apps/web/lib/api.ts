import { getToken, clearSession } from "@/lib/auth";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface User {
  id: string;
  email: string | null;
  name: string | null;
  avatar_url: string | null;
  created_at: string;
}

export interface AuthOut {
  token: string;
  user: User;
}

export interface Project {
  id: string;
  name: string;
  owner_id: string;
  created_at: string;
  github_login: string | null;
  github_connected: boolean;
  slack_team_name: string | null;
  slack_connected: boolean;
  discord_guild_name: string | null;
  discord_connected: boolean;
  liveagent_base_url: string | null;
  liveagent_connected: boolean;
  stripe_account_name: string | null;
  stripe_connected: boolean;
}

export interface Source {
  id: string;
  org_id: string;
  kind: string;
  config: Record<string, unknown>;
  status: string;
  cursor: string | null;
  last_sync_at: string | null;
  last_error: string | null;
  created_at: string;
  has_secret: boolean;
  event_count: number;
}

export interface McpInfo {
  endpoint: string;
  token: string;
}

export interface Analytics {
  events_per_day: number[];
  total_events: number;
  total_builds: number;
  context_bytes: number;
  sources_live: number;
  days: number;
}

export interface McpRequest {
  id: string;
  tool: string;
  params: unknown;
  status: string;
  response: unknown | null;
  error: string | null;
  duration_ms: number;
  created_at: string;
}

export interface McpStats {
  requests_per_day: number[];
  total_requests: number;
  total_errors: number;
  avg_duration_ms: number;
  by_tool: Record<string, number>;
  days: number;
}

export interface IngestedEvent {
  event_id: string;
  source: string;
  type: string;
  subject: string;
  event_time: string;
  ingest_time: string;
}

export interface Build {
  org_id: string;
  dedupe_key: string;
  lane: string;
  status: string;
  snapshot_id: string | null;
  attempts: number;
  last_error: string | null;
  updated_at: string;
}

export interface Health {
  ok: boolean;
  kinds: string[];
  oauth: { github: boolean; slack: boolean; discord: boolean; google: boolean };
}

export interface FsList {
  files: string[];
  snapshot_id: string | null;
}

export interface FsFile {
  path: string;
  content: string;
  size: number;
}

export interface FsWriteResult {
  path: string;
  size: number;
  snapshot_id: string;
}

export interface Repo {
  full_name: string;
}
export interface Channel {
  id: string;
  name: string;
}
export interface Department {
  id: string;
  name: string;
}
export interface Tag {
  id: string;
  name: string;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...((init?.headers as Record<string, string>) ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401) {
    clearSession();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const text = await res.text();
    let msg = text;
    try {
      const j = JSON.parse(text);
      if (j && typeof j.detail === "string") msg = j.detail;
    } catch {
      /* body wasn't JSON — fall back to raw text */
    }
    throw new Error(msg || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const fetcher = <T>(path: string) => req<T>(path);

export const api = {
  health: () => req<Health>("/health"),

  register: (email: string, password: string, name: string) =>
    req<AuthOut>("/auth/register", json({ email, password, name })),
  login: (email: string, password: string) => req<AuthOut>("/auth/login", json({ email, password })),
  me: () => req<User>("/auth/me"),
  googleStartUrl: () => `${API_BASE}/auth/google/start`,

  createProject: (name: string) => req<Project>("/projects", json({ name })),
  listProjects: () => req<Project[]>("/projects"),
  getProject: (id: string) => req<Project>(`/projects/${id}`),
  deleteProject: (id: string) => req<unknown>(`/projects/${id}`, { method: "DELETE" }),
  renameProject: (id: string, name: string) =>
    req<Project>(`/projects/${id}`, { ...json({ name }), method: "PATCH" }),
  getAnalytics: (id: string) => req<Analytics>(`/projects/${id}/analytics`),
  getMcpInfo: (id: string) => req<McpInfo>(`/projects/${id}/mcp`),
  disconnectProvider: (id: string, provider: string) =>
    req<unknown>(`/projects/${id}/integrations/${provider}`, { method: "DELETE" }),

  oauthStartUrl: (provider: string, projectId: string) =>
    `${API_BASE}/oauth/${provider}/start?project_id=${projectId}`,
  listRepos: (projectId: string) => req<Repo[]>(`/oauth/github/repos?project_id=${projectId}`),
  listChannels: (projectId: string) =>
    req<Channel[]>(`/oauth/slack/channels?project_id=${projectId}`),

  // LiveAgent (no OAuth): store base URL + v3 API key, then list departments/tags.
  connectLiveAgent: (projectId: string, base_url: string, api_key: string) =>
    req<Project>(`/projects/${projectId}/integrations/liveagent`, {
      ...json({ base_url, api_key }),
      method: "PUT",
    }),
  listDepartments: (projectId: string) =>
    req<Department[]>(`/liveagent/departments?project_id=${projectId}`),
  listTags: (projectId: string) => req<Tag[]>(`/liveagent/tags?project_id=${projectId}`),

  // Stripe (no OAuth): store a read-only Restricted key; all events are then indexed.
  connectStripe: (projectId: string, api_key: string) =>
    req<Project>(`/projects/${projectId}/integrations/stripe`, {
      ...json({ api_key }),
      method: "PUT",
    }),

  // Context filesystem — the agent's working files (browse + edit).
  listFs: (projectId: string) => req<FsList>(`/projects/${projectId}/fs`),
  readFile: (projectId: string, path: string) =>
    req<FsFile>(`/projects/${projectId}/fs/file?path=${encodeURIComponent(path)}`),
  writeFile: (projectId: string, path: string, content: string) =>
    req<FsWriteResult>(`/projects/${projectId}/fs/file`, {
      ...json({ path, content }),
      method: "PUT",
    }),

  createSource: (
    project_id: string,
    kind: string,
    config: Record<string, unknown>,
    secret?: string | null,
  ) => req<Source>("/sources", json({ project_id, kind, config, secret: secret ?? null })),
  listSources: (projectId: string) => req<Source[]>(`/sources?project_id=${projectId}`),
  syncSource: (id: string) => req<{ ingested: number }>(`/sources/${id}/sync`, { method: "POST" }),
  deleteSource: (id: string) => req<unknown>(`/sources/${id}`, { method: "DELETE" }),
};
