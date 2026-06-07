export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface User {
  id: string;
  username: string;
  created_at: string;
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
  oauth: { github: boolean; slack: boolean };
}

export interface Repo {
  full_name: string;
}
export interface Channel {
  id: string;
  name: string;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
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
  login: (username: string) => req<User>("/auth/login", json({ username })),

  createProject: (owner_id: string, name: string) =>
    req<Project>("/projects", json({ owner_id, name })),
  listProjects: (owner_id: string) => req<Project[]>(`/projects?owner_id=${owner_id}`),
  getProject: (id: string) => req<Project>(`/projects/${id}`),
  deleteProject: (id: string) => req<unknown>(`/projects/${id}`, { method: "DELETE" }),

  oauthStartUrl: (provider: string, projectId: string) =>
    `${API_BASE}/oauth/${provider}/start?project_id=${projectId}`,
  listRepos: (projectId: string) => req<Repo[]>(`/oauth/github/repos?project_id=${projectId}`),
  listChannels: (projectId: string) =>
    req<Channel[]>(`/oauth/slack/channels?project_id=${projectId}`),

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
