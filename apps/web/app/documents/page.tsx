"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { DocumentMap as DocumentMapData, DocumentPoint } from "@/lib/types";

// Canvas touches `window`; render client-only.
const DocumentMap = dynamic(() => import("./DocumentMap"), { ssr: false });

export default function DocumentsPage() {
  const [limit, setLimit] = useState(500);
  const [selected, setSelected] = useState<DocumentPoint | null>(null);

  const { data, error, isLoading, mutate } = useSWR<DocumentMapData>(
    `/api/v1/documents/vectors?limit=${limit}`,
    fetcher,
    { refreshInterval: 10000 },
  );

  const sourceCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const p of data?.points ?? []) {
      counts.set(p.source, (counts.get(p.source) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [data]);

  const var1 = data ? Math.round((data.variance_explained[0] ?? 0) * 100) : 0;
  const var2 = data ? Math.round((data.variance_explained[1] ?? 0) * 100) : 0;

  return (
    <div className="h-[calc(100vh-3.5rem)] grid grid-cols-[1fr_320px]">
      <section className="relative bg-black/[0.02] dark:bg-white/[0.02] border-r border-black/10 dark:border-white/10">
        <div className="absolute top-2 left-2 z-10 flex items-center gap-2 bg-white/90 dark:bg-black/70 rounded-md px-2 py-1 text-xs border border-black/10 dark:border-white/15">
          <label className="opacity-70">last N docs</label>
          <input
            type="number"
            min={1}
            max={5000}
            value={limit}
            onChange={(e) => setLimit(Math.max(1, Number(e.target.value) || 1))}
            className="w-20 bg-transparent border-b border-black/20 dark:border-white/20 outline-none"
          />
          <button
            type="button"
            onClick={() => mutate()}
            className="px-2 py-0.5 rounded border border-black/10 dark:border-white/15 hover:bg-black/5 dark:hover:bg-white/5"
          >
            refresh
          </button>
          {data && (
            <span className="opacity-60">
              {data.points.length} docs · PC1 {var1}% · PC2 {var2}%
            </span>
          )}
        </div>

        {isLoading && (
          <div className="absolute inset-0 grid place-items-center text-sm opacity-70">loading…</div>
        )}
        {error && (
          <div className="absolute inset-0 grid place-items-center text-sm text-red-600 dark:text-red-400 px-6 text-center">
            {String((error as Error).message ?? error)}
          </div>
        )}
        {data && data.points.length === 0 && (
          <div className="absolute inset-0 grid place-items-center text-sm opacity-70 px-6 text-center">
            No embedded documents yet. Ingest something via{" "}
            <Link href="/ingest" className="underline ml-1">/ingest</Link>.
          </div>
        )}
        {data && data.points.length > 0 && (
          <DocumentMap
            points={data.points}
            selectedId={selected?.event_id ?? null}
            onSelect={(p) => setSelected(p)}
          />
        )}
      </section>

      <aside className="overflow-y-auto p-4 space-y-5 text-sm">
        <div>
          <h2 className="font-medium mb-2">Sources</h2>
          {sourceCounts.length === 0 && <p className="text-xs opacity-60">none</p>}
          <ul className="space-y-1">
            {sourceCounts.map(([src, n]) => (
              <li key={src} className="flex items-center gap-2 text-xs">
                <span
                  className="inline-block w-3 h-3 rounded-full"
                  style={{ background: colorFor(src) }}
                />
                <code className="flex-1 truncate">{src}</code>
                <span className="opacity-60">{n}</span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h2 className="font-medium mb-2">Selection</h2>
          {!selected && <p className="text-xs opacity-60">click a point on the map.</p>}
          {selected && (
            <div className="space-y-2">
              <div className="text-xs uppercase tracking-wide opacity-50">Document</div>
              <div className="font-medium break-all">{selected.subject}</div>
              <div className="flex flex-wrap gap-1 text-xs">
                <span className="px-2 py-0.5 rounded bg-black/5 dark:bg-white/10">{selected.source}</span>
                <span className="px-2 py-0.5 rounded bg-black/5 dark:bg-white/10">{selected.type}</span>
              </div>
              {selected.text_preview && (
                <p className="opacity-80 text-xs whitespace-pre-wrap">
                  {selected.text_preview}
                </p>
              )}
              <div className="text-xs opacity-60">
                ingested {new Date(selected.ingest_time).toLocaleString()}
              </div>
              <Link
                href={`/events/${encodeURIComponent(selected.event_id)}`}
                className="text-xs underline opacity-80"
              >
                open event →
              </Link>
            </div>
          )}
        </div>

        <div className="text-xs opacity-50 pt-3 border-t border-black/10 dark:border-white/10">
          Each point is one ingested document embedded by the worker and stored
          in the per-tenant FAISS index. Position comes from a 2D PCA projection
          of the embedding space, so spatial nearness ≈ semantic similarity.
        </div>
      </aside>
    </div>
  );
}

// Mirror of DocumentMap.tsx#colorFor — keeps the legend swatches in sync.
const PALETTE = [
  "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#06b6d4",
  "#a855f7", "#ec4899", "#14b8a6", "#f97316", "#84cc16",
];
function colorFor(source: string): string {
  let h = 0;
  for (let i = 0; i < source.length; i++) h = (h * 31 + source.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
