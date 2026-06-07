"use client";

import { useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import {
  api,
  fetcher,
  type Build,
  type Health,
  type IngestedEvent,
  type Project,
  type Source,
} from "@/lib/api";
import { useUser } from "@/lib/auth";
import { Badge, Button, Card } from "@/components/ui";
import { Integration } from "@/components/Integration";

export default function ProjectDashboard() {
  const user = useUser();
  const params = useParams<{ id: string }>();
  const id = params.id;
  const search = useSearchParams();

  const project = useSWR<Project>(`/projects/${id}`, fetcher, { refreshInterval: 5000 });
  const sources = useSWR<Source[]>(`/sources?project_id=${id}`, fetcher, { refreshInterval: 4000 });
  const events = useSWR<IngestedEvent[]>(`/events?project_id=${id}&limit=25`, fetcher, { refreshInterval: 4000 });
  const builds = useSWR<Build[]>(`/builds?project_id=${id}&limit=25`, fetcher, { refreshInterval: 4000 });
  const health = useSWR<Health>("/health", fetcher);

  const [syncing, setSyncing] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  if (!user) return null;

  const refresh = () => {
    project.mutate();
    sources.mutate();
    events.mutate();
    builds.mutate();
  };

  const connected = search.get("connected");
  const error = search.get("error");

  async function doSync(sourceId: string) {
    setSyncing(sourceId);
    setNote(null);
    try {
      const { ingested } = await api.syncSource(sourceId);
      setNote(`Synced ${ingested} event(s) — they're flowing through the engine now.`);
      refresh();
    } catch (e) {
      setNote(`Sync failed: ${e}`);
    } finally {
      setSyncing(null);
    }
  }

  if (!project.data) return <p className="text-sm text-neutral-500">Loading…</p>;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <Link href="/projects" className="text-sm text-neutral-400 hover:underline">
            ← Projects
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{project.data.name}</h1>
        </div>
      </div>

      {connected && (
        <div className="rounded-lg border border-emerald-700/40 bg-emerald-950/30 px-4 py-3 text-sm text-emerald-300">
          Connected {connected}. Pick a {connected === "github" ? "repo" : "channel"} below to start ingesting.
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-red-700/40 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          {error === "oauth_not_configured"
            ? "OAuth isn't configured for this provider — use “advanced: add manually”, or set the OAuth client id/secret in .env."
            : `Connect failed: ${error}`}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Integration provider="github" project={project.data} oauthConfigured={!!health.data?.oauth.github} onChanged={refresh} />
        <Integration provider="slack" project={project.data} oauthConfigured={!!health.data?.oauth.slack} onChanged={refresh} />
      </div>

      <Card title="Sources">
        {!sources.data?.length ? (
          <p className="text-sm text-neutral-500">No sources connected yet.</p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {sources.data.map((s) => (
                <tr key={s.id} className="border-t border-neutral-800 first:border-t-0">
                  <td className="py-2">{s.kind}</td>
                  <td className="py-2 font-mono text-xs text-neutral-300">{JSON.stringify(s.config)}</td>
                  <td className="py-2">
                    <Badge value={s.status} />
                    {s.last_error && <span className="ml-2 text-xs text-red-400">{s.last_error.slice(0, 50)}</span>}
                  </td>
                  <td className="py-2 text-xs text-neutral-500">
                    {s.last_sync_at ? new Date(s.last_sync_at).toLocaleTimeString() : "never"}
                  </td>
                  <td className="py-2 text-right">
                    <span className="inline-flex gap-2">
                      <Button variant="ghost" disabled={syncing === s.id} onClick={() => doSync(s.id)}>
                        {syncing === s.id ? "Syncing…" : "Sync now"}
                      </Button>
                      <Button variant="danger" onClick={async () => { await api.deleteSource(s.id); refresh(); }}>
                        Remove
                      </Button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {note && <p className="mt-3 text-sm text-neutral-400">{note}</p>}
      </Card>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card title="Recent events (ingested)">
          {!events.data?.length ? (
            <p className="text-sm text-neutral-500">No events yet — connect a source and sync.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {events.data.map((e) => (
                <li key={e.event_id} className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-xs text-neutral-300">{e.type}</span>
                  <span className="truncate text-xs text-neutral-500">{e.subject}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Context builds">
          {!builds.data?.length ? (
            <p className="text-sm text-neutral-500">No builds yet.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {builds.data.map((b) => (
                <li key={`${b.lane}-${b.dedupe_key}`} className="flex items-center justify-between gap-2">
                  <span className="inline-flex gap-2">
                    <Badge value={b.lane} />
                    <Badge value={b.status} />
                  </span>
                  <span className="truncate font-mono text-xs text-neutral-500">{b.dedupe_key.slice(0, 24)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
