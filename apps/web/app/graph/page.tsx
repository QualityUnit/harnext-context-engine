"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { GraphResponse } from "@/lib/types";

// Cytoscape touches `window`; render only on the client.
const GraphView = dynamic(() => import("./GraphView"), { ssr: false });

export default function GraphPage() {
  const [lastN, setLastN] = useState(20);
  const [selected, setSelected] = useState<string | null>(null);

  const { data, error, isLoading, mutate } = useSWR<GraphResponse>(
    `/api/v1/graph?last_n=${lastN}`,
    fetcher,
  );

  const selectedNode = data?.nodes.find((n) => n.id === selected);
  const selectedEdge = data?.edges.find((e) => e.id === selected);

  return (
    <div className="h-[calc(100vh-3.5rem)] grid grid-cols-[1fr_320px]">
      <section className="relative bg-black/[0.02] dark:bg-white/[0.02] border-r border-black/10 dark:border-white/10">
        {/* Toolbar */}
        <div className="absolute top-2 left-2 z-10 flex items-center gap-2 bg-white/90 dark:bg-black/70 rounded-md px-2 py-1 text-xs border border-black/10 dark:border-white/15">
          <label className="opacity-70">last N episodes</label>
          <input
            type="number"
            min={1}
            max={200}
            value={lastN}
            onChange={(e) => setLastN(Math.max(1, Number(e.target.value) || 1))}
            className="w-16 bg-transparent border-b border-black/20 dark:border-white/20 outline-none"
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
              {data.nodes.length} nodes · {data.edges.length} edges
            </span>
          )}
        </div>

        {isLoading && (
          <div className="absolute inset-0 grid place-items-center text-sm opacity-70">loading…</div>
        )}
        {error && (
          <div className="absolute inset-0 grid place-items-center text-sm text-red-600 dark:text-red-400 px-6 text-center">
            {String(error.message ?? error)}
          </div>
        )}
        {data && data.nodes.length === 0 && (
          <div className="absolute inset-0 grid place-items-center text-sm opacity-70 px-6 text-center">
            No graph yet. Ingest some events to populate.
          </div>
        )}
        {data && data.nodes.length > 0 && (
          <GraphView data={data} onSelect={(id) => setSelected(id)} />
        )}
      </section>

      <aside className="overflow-y-auto p-4">
        <h2 className="font-medium mb-2">Selection</h2>
        {!selected && <p className="text-sm opacity-60">click a node or edge.</p>}
        {selectedNode && (
          <div className="space-y-2 text-sm">
            <div className="text-xs uppercase tracking-wide opacity-50">Entity</div>
            <div className="font-medium">{selectedNode.name}</div>
            {selectedNode.summary && <p className="opacity-80">{selectedNode.summary}</p>}
            {selectedNode.labels.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {selectedNode.labels.map((l) => (
                  <span key={l} className="text-xs px-2 py-0.5 rounded bg-black/5 dark:bg-white/10">{l}</span>
                ))}
              </div>
            )}
            <div className="text-xs opacity-50 break-all font-mono">{selectedNode.id}</div>
          </div>
        )}
        {selectedEdge && (
          <div className="space-y-2 text-sm">
            <div className="text-xs uppercase tracking-wide opacity-50">Fact</div>
            <p>{selectedEdge.fact}</p>
            {selectedEdge.valid_at && (
              <div className="text-xs opacity-60">
                valid from {new Date(selectedEdge.valid_at).toLocaleString()}
              </div>
            )}
            <div className="text-xs opacity-50 break-all font-mono">{selectedEdge.id}</div>
          </div>
        )}
      </aside>
    </div>
  );
}
