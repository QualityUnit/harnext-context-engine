"use client";

import { use } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { EventDetail } from "@/lib/types";

export default function EventDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const decoded = decodeURIComponent(id);
  const { data, error, isLoading } = useSWR<EventDetail>(
    `/api/v1/events/${encodeURIComponent(decoded)}`,
    fetcher,
    { refreshInterval: 3000 },
  );

  return (
    <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight break-all">{decoded}</h1>
        {data && (
          <p className="text-sm opacity-70 mt-1">
            <code>{data.source}</code> · <code>{data.type}</code> · <code>{data.subject}</code>
          </p>
        )}
      </div>

      {isLoading && <p className="opacity-70 text-sm">loading…</p>}
      {error && <p className="text-sm text-red-600 dark:text-red-400">error: {String(error.message ?? error)}</p>}

      {data && (
        <>
          <section className="space-y-2">
            <h2 className="font-medium">Sink status</h2>
            {data.sinks.length === 0 ? (
              <p className="text-sm opacity-60">no sink outcomes recorded yet — worker may not have processed this event.</p>
            ) : (
              <div className="rounded-lg border border-black/10 dark:border-white/10 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-black/[0.03] dark:bg-white/[0.04] text-left">
                    <tr>
                      <th className="px-3 py-2 font-medium">Sink</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                      <th className="px-3 py-2 font-medium">Attempts</th>
                      <th className="px-3 py-2 font-medium">Completed</th>
                      <th className="px-3 py-2 font-medium">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sinks.map((s) => (
                      <tr key={s.sink} className="border-t border-black/10 dark:border-white/10">
                        <td className="px-3 py-2"><code>{s.sink}</code></td>
                        <td className="px-3 py-2">
                          <span
                            className={
                              s.status === "success"
                                ? "text-emerald-600 dark:text-emerald-400"
                                : s.status === "failed"
                                  ? "text-red-600 dark:text-red-400"
                                  : "opacity-70"
                            }
                          >
                            {s.status}
                          </span>
                        </td>
                        <td className="px-3 py-2">{s.attempts}</td>
                        <td className="px-3 py-2 opacity-80">
                          {s.completed_at ? new Date(s.completed_at).toLocaleString() : "—"}
                        </td>
                        <td className="px-3 py-2 text-xs opacity-80 max-w-md truncate">
                          {s.last_error ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="space-y-2">
            <h2 className="font-medium">Envelope</h2>
            <pre className="text-xs bg-black/[0.04] dark:bg-white/[0.04] rounded-lg p-4 overflow-auto">
              {JSON.stringify(JSON.parse(data.envelope_json), null, 2)}
            </pre>
          </section>
        </>
      )}
    </div>
  );
}
