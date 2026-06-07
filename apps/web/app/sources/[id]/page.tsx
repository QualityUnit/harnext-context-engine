"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { fetcher, syncSource, type Source } from "@/lib/api";
import { Badge, Button, Card, Link } from "@/components/ui";

export default function SourceDetail() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data: source, mutate } = useSWR<Source>(`/sources/${id}`, fetcher, { refreshInterval: 4000 });
  const [syncing, setSyncing] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function doSync() {
    setSyncing(true);
    setNote(null);
    try {
      const { ingested } = await syncSource(id);
      setNote(`Synced: ${ingested} event(s).`);
      mutate();
    } catch (e) {
      setNote(`Sync failed: ${e}`);
    } finally {
      setSyncing(false);
    }
  }

  if (!source) return <p className="text-sm text-neutral-500">Loading…</p>;

  return (
    <div className="flex flex-col gap-6">
      <Link href="/sources" className="text-sm text-neutral-400 hover:underline">
        ← Back to sources
      </Link>
      <Card
        title={`${source.kind} source`}
        action={
          <Button variant="ghost" disabled={syncing} onClick={doSync}>
            {syncing ? "Syncing…" : "Sync now"}
          </Button>
        }
      >
        <dl className="grid grid-cols-3 gap-y-3 text-sm">
          <dt className="text-neutral-500">Org</dt>
          <dd className="col-span-2">{source.org_id}</dd>
          <dt className="text-neutral-500">Config</dt>
          <dd className="col-span-2 font-mono text-xs">{JSON.stringify(source.config)}</dd>
          <dt className="text-neutral-500">Status</dt>
          <dd className="col-span-2">
            <Badge value={source.status} />
          </dd>
          <dt className="text-neutral-500">Cursor</dt>
          <dd className="col-span-2 font-mono text-xs text-neutral-400">{source.cursor ?? "—"}</dd>
          <dt className="text-neutral-500">Last sync</dt>
          <dd className="col-span-2 text-neutral-400">
            {source.last_sync_at ? new Date(source.last_sync_at).toLocaleString() : "never"}
          </dd>
          <dt className="text-neutral-500">Token</dt>
          <dd className="col-span-2">{source.has_secret ? "set" : "none"}</dd>
          {source.last_error && (
            <>
              <dt className="text-neutral-500">Last error</dt>
              <dd className="col-span-2 text-red-400">{source.last_error}</dd>
            </>
          )}
        </dl>
        {note && <p className="mt-4 text-sm text-neutral-400">{note}</p>}
      </Card>
    </div>
  );
}
