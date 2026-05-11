"use client";

import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { EventSummary } from "@/lib/types";

export default function EventsPage() {
  const { data, error, isLoading } = useSWR<EventSummary[]>(
    "/api/v1/events?limit=100",
    fetcher,
    { refreshInterval: 5000 },
  );

  return (
    <div className="max-w-6xl mx-auto px-6 py-8 space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Events</h1>
        <span className="text-xs opacity-50">auto-refresh 5s</span>
      </div>

      {isLoading && <p className="opacity-70 text-sm">loading…</p>}
      {error && (
        <p className="text-sm text-red-600 dark:text-red-400">
          error: {String(error.message ?? error)}
        </p>
      )}

      {data && data.length === 0 && (
        <div className="rounded-lg border border-dashed border-black/15 dark:border-white/15 p-8 text-center">
          <p className="opacity-70 text-sm">No events yet.</p>
          <p className="opacity-50 text-xs mt-1">
            Try <Link href="/ingest" className="underline">/ingest</Link> to add one.
          </p>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-black/10 dark:border-white/10">
          <table className="w-full text-sm">
            <thead className="bg-black/[0.03] dark:bg-white/[0.04] text-left">
              <tr>
                <th className="px-3 py-2 font-medium">Ingest time</th>
                <th className="px-3 py-2 font-medium">Source</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Subject</th>
                <th className="px-3 py-2 font-medium">Blob</th>
                <th className="px-3 py-2 font-medium">Id</th>
              </tr>
            </thead>
            <tbody>
              {data.map((e) => (
                <tr
                  key={e.id}
                  className="border-t border-black/10 dark:border-white/10 hover:bg-black/[0.02] dark:hover:bg-white/[0.03]"
                >
                  <td className="px-3 py-2 whitespace-nowrap opacity-80">
                    {new Date(e.ingest_time).toLocaleString()}
                  </td>
                  <td className="px-3 py-2"><code>{e.source}</code></td>
                  <td className="px-3 py-2"><code>{e.type}</code></td>
                  <td className="px-3 py-2"><code>{e.subject}</code></td>
                  <td className="px-3 py-2">{e.has_blob ? "yes" : "—"}</td>
                  <td className="px-3 py-2">
                    <Link
                      href={`/events/${encodeURIComponent(e.id)}`}
                      className="font-mono text-xs underline opacity-80"
                    >
                      {e.id.length > 40 ? e.id.slice(0, 40) + "…" : e.id}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
