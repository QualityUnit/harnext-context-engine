export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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

export interface SourceCreate {
  org_id: string;
  kind: string;
  config: Record<string, unknown>;
  secret: string | null;
}

export const fetcher = async <T>(path: string): Promise<T> => {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
};

export async function createSource(body: SourceCreate): Promise<Source> {
  const res = await fetch(`${API_BASE}/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function syncSource(id: string): Promise<{ ingested: number }> {
  const res = await fetch(`${API_BASE}/sources/${id}/sync`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteSource(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sources/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}
