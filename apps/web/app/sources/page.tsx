"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import {
  fetcher,
  syncSource,
  deleteSource,
  type Build,
  type IngestedEvent,
  type Source,
} from "@/lib/api";
import { AddSourceForm } from "@/components/AddSourceForm";
import { Badge, Button, Card, Field, Link, inputCls } from "@/components/ui";

export default function SourcesPage() {
  const [orgId, setOrgId] = useState("acme");
  useEffect(() => {
    const saved = localStorage.getItem("mg.org");
    if (saved) setOrgId(saved);
  }, []);
  useEffect(() => {
    localStorage.setItem("mg.org", orgId);
  }, [orgId]);

  const sources = useSWR<Source[]>(`/sources?org_id=${orgId}`, fetcher, { refreshInterval: 4000 });
  const events = useSWR<IngestedEvent[]>(`/events?org_id=${orgId}&limit=25`, fetcher, { refreshInterval: 4000 });
  const builds = useSWR<Build[]>(`/builds?org_id=${orgId}&limit=25`, fetcher, { refreshInterval: 4000 });

  const refresh = () => {
    sources.mutate();
    events.mutate();
    builds.mutate();
  };

  const [syncing, setSyncing] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function doSync(id: string) {
    setSyncing(id);
    setNote(null);
    try {
      const { ingested } = await syncSource(id);
      setNote(`Synced: ${ingested} event(s) ingested.`);
      refresh();
    } catch (e) {
      setNote(`Sync failed: ${e}`);
    } finally {
      setSyncing(null);
    }
  }

  async function doDelete(id: string) {
    await deleteSource(id);
    refresh();
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between">
        <Field label="Organization">
          <input className={inputCls} value={orgId} onChange={(e) => setOrgId(e.target.value)} />
        </Field>
        {note && <p className="text-sm text-neutral-400">{note}</p>}
      </div>

      <Card title="Connect a source">
        <AddSourceForm orgId={orgId} onAdded={refresh} />
      </Card>

      <Card title="Sources">
        {!sources.data?.length ? (
          <p className="text-sm text-neutral-500">No sources yet. Connect one above.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-neutral-500">
              <tr>
                <th className="pb-2">Kind</th>
                <th className="pb-2">Config</th>
                <th className="pb-2">Status</th>
                <th className="pb-2">Last sync</th>
                <th className="pb-2"></th>
              </tr>
            </thead>
            <tbody>
              {sources.data.map((s) => (
                <tr key={s.id} className="border-t border-neutral-800">
                  <td className="py-2">{s.kind}</td>
                  <td className="py-2 font-mono text-xs text-neutral-300">
                    <Link href={`/sources/${s.id}`} className="hover:underline">
                      {JSON.stringify(s.config)}
                    </Link>
                  </td>
                  <td className="py-2">
                    <Badge value={s.status} />
                    {s.last_error && <span className="ml-2 text-xs text-red-400">{s.last_error.slice(0, 60)}</span>}
                  </td>
                  <td className="py-2 text-xs text-neutral-400">
                    {s.last_sync_at ? new Date(s.last_sync_at).toLocaleString() : "never"}
                  </td>
                  <td className="py-2 text-right">
                    <span className="inline-flex gap-2">
                      <Button variant="ghost" disabled={syncing === s.id} onClick={() => doSync(s.id)}>
                        {syncing === s.id ? "Syncing…" : "Sync now"}
                      </Button>
                      <Button variant="danger" onClick={() => doDelete(s.id)}>
                        Delete
                      </Button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card title="Recent events (ingested)">
          {!events.data?.length ? (
            <p className="text-sm text-neutral-500">No events yet.</p>
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

        <Card title="Recent builds (context updates)">
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
                  <span className="truncate font-mono text-xs text-neutral-500">{b.dedupe_key.slice(0, 28)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
