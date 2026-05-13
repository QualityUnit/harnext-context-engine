"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, ArrowRight, Loader2, RefreshCw, X } from "lucide-react";

import {
  NexusDivider,
  NexusSection,
  NexusShell,
  NexusToolbar,
} from "@/components/nexus-shell";
import {
  MultiSelectFilter,
  TimeRangeFilter,
  type TimeRangeKey,
  withinTimeRange,
} from "@/components/filter-panel";
import { fetcher } from "@/lib/api";
import { colorFor } from "@/lib/colors";
import type { GraphEdge, GraphNode, GraphResponse } from "@/lib/types";

const GraphView = dynamic(() => import("./GraphView"), { ssr: false });

export default function GraphPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [labels, setLabels] = useState<Set<string> | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRangeKey>("all");

  // No `?last_n=` — API returns every entity + edge for the tenant. Filter
  // sections in the rail narrow client-side; that's the only place limits
  // should come from.
  const { data, error, isLoading, mutate, isValidating } = useSWR<GraphResponse>(
    `/api/v1/graph`,
    fetcher,
  );

  const allNodes = data?.nodes ?? [];
  const allEdges = data?.edges ?? [];

  // Label option list (counts per label across all nodes).
  const labelOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of allNodes) {
      for (const l of n.labels) counts.set(l, (counts.get(l) ?? 0) + 1);
    }
    return Array.from(counts, ([key, count]) => ({ key, count })).sort(
      (a, b) => b.count - a.count,
    );
  }, [allNodes]);

  const visibleNodes = useMemo(() => {
    if (labels === null) return allNodes;
    return allNodes.filter((n) => n.labels.some((l) => labels.has(l)));
  }, [allNodes, labels]);

  const visibleNodeIds = useMemo(
    () => new Set(visibleNodes.map((n) => n.id)),
    [visibleNodes],
  );

  const visibleEdges = useMemo(() => {
    return allEdges.filter(
      (e) =>
        visibleNodeIds.has(e.source) &&
        visibleNodeIds.has(e.target) &&
        withinTimeRange(e.valid_at, timeRange),
    );
  }, [allEdges, visibleNodeIds, timeRange]);

  const filteredGraph = useMemo<GraphResponse>(
    () => ({ nodes: visibleNodes, edges: visibleEdges }),
    [visibleNodes, visibleEdges],
  );

  const selectedNode = data?.nodes.find((n) => n.id === selected) ?? null;
  const selectedEdge = data?.edges.find((e) => e.id === selected) ?? null;
  const hasSelection = !!(selectedNode || selectedEdge);

  return (
    <NexusShell
      hasSelection={hasSelection}
      filters={
        <>
          <NexusSection title="Labels">
            <MultiSelectFilter
              options={labelOptions}
              selected={labels}
              onChange={setLabels}
              searchable
              emptyHint="No labels in the graph yet."
              colored
            />
          </NexusSection>
          <NexusDivider />
          <NexusSection
            title="Time (edges)"
            hint={
              <>
                Filters facts by their <code>valid_at</code> timestamp.
              </>
            }
          >
            <TimeRangeFilter value={timeRange} onChange={setTimeRange} />
          </NexusSection>
        </>
      }
      inspector={
        hasSelection ? (
          <GraphInspector
            node={selectedNode}
            edge={selectedEdge}
            allNodes={allNodes}
            allEdges={allEdges}
            onPickEntity={(id) => setSelected(id)}
            onClear={() => setSelected(null)}
          />
        ) : null
      }
      toolbar={
        <NexusToolbar>
          <button
            type="button"
            onClick={() => mutate()}
            disabled={isValidating}
            className="flex items-center gap-1.5 rounded px-2 py-1 text-[12px] transition-colors disabled:opacity-50"
            style={{ color: "var(--nx-text-secondary)" }}
          >
            <RefreshCw
              className={"h-3.5 w-3.5 " + (isValidating ? "animate-spin" : "")}
            />
            Refresh
          </button>
          <span style={{ color: "var(--nx-border-default)" }}>·</span>
          {data && (
            <span
              className="text-[12px] tabular-nums"
              style={{ color: "var(--nx-text-secondary)" }}
            >
              {visibleNodes.length} / {allNodes.length} nodes ·{" "}
              {visibleEdges.length} / {allEdges.length} edges
            </span>
          )}
        </NexusToolbar>
      }
      statusLeft={
        <>
          <span>
            <span style={{ color: "var(--nx-text-primary)" }} className="tabular-nums">
              {visibleNodes.length}
            </span>{" "}
            / <span className="tabular-nums">{allNodes.length}</span> nodes
          </span>
          <span style={{ color: "var(--nx-border-default)" }}>·</span>
          <span>
            <span style={{ color: "var(--nx-text-primary)" }} className="tabular-nums">
              {visibleEdges.length}
            </span>{" "}
            / <span className="tabular-nums">{allEdges.length}</span> edges
          </span>
          <span style={{ color: "var(--nx-border-default)" }}>·</span>
          <span>
            {labels === null
              ? "All labels"
              : `${labels.size}/${labelOptions.length} labels`}
          </span>
          <span style={{ color: "var(--nx-border-default)" }}>·</span>
          <span>{timeRange === "all" ? "All time" : timeRange}</span>
        </>
      }
    >
      {isLoading && (
        <div
          className="absolute inset-0 grid place-items-center text-sm"
          style={{ color: "var(--nx-text-muted)" }}
        >
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      )}
      {error && (
        <div
          className="absolute inset-0 grid place-items-center px-6 text-center text-sm"
          style={{ color: "#f87171" }}
        >
          {String((error as Error).message ?? error)}
        </div>
      )}
      {data && allNodes.length === 0 && (
        <div
          className="absolute inset-0 grid place-items-center px-6 text-center text-sm"
          style={{ color: "var(--nx-text-muted)" }}
        >
          No graph yet. Ingest some events to populate.
        </div>
      )}
      {data && allNodes.length > 0 && visibleNodes.length === 0 && (
        <div
          className="absolute inset-0 grid place-items-center px-6 text-center text-sm"
          style={{ color: "var(--nx-text-muted)" }}
        >
          No nodes match the current filters.
        </div>
      )}
      {data && visibleNodes.length > 0 && (
        <GraphView
          data={filteredGraph}
          selectedId={selected}
          onSelect={(id) => setSelected(id)}
        />
      )}
    </NexusShell>
  );
}

function GraphInspector({
  node,
  edge,
  allNodes,
  allEdges,
  onPickEntity,
  onClear,
}: {
  node: GraphNode | null;
  edge: GraphEdge | null;
  allNodes: GraphNode[];
  allEdges: GraphEdge[];
  onPickEntity: (id: string) => void;
  onClear: () => void;
}) {
  const nodeById = useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of allNodes) m.set(n.id, n);
    return m;
  }, [allNodes]);

  const outgoing = useMemo(
    () => (node ? allEdges.filter((e) => e.source === node.id) : []),
    [node, allEdges],
  );
  const incoming = useMemo(
    () => (node ? allEdges.filter((e) => e.target === node.id) : []),
    [node, allEdges],
  );

  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div
            className="text-[11px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--nx-text-muted)" }}
          >
            {node ? "Entity" : "Fact"}
          </div>
          <div
            className="mt-1 break-words text-xs font-semibold"
            style={{ color: "var(--nx-text-primary)" }}
          >
            {node?.name ?? edge?.fact}
          </div>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="rounded p-1 transition-colors"
          style={{ color: "var(--nx-text-muted)" }}
          aria-label="Clear selection"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {node?.summary && (
        <p
          className="rounded border p-2 text-[12px] leading-relaxed"
          style={{
            backgroundColor: "var(--nx-elevated)",
            borderColor: "var(--nx-border-subtle)",
            color: "var(--nx-text-secondary)",
          }}
        >
          {node.summary}
        </p>
      )}

      {node && node.labels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {node.labels.map((l) => (
            <span
              key={l}
              className="rounded px-1.5 py-0.5 text-[11px]"
              style={{
                backgroundColor: colorFor(l) + "22",
                color: colorFor(l),
              }}
            >
              {l}
            </span>
          ))}
        </div>
      )}

      {node && (
        <>
          <NexusFactsHeader
            outgoingCount={outgoing.length}
            incomingCount={incoming.length}
          />
          {outgoing.length === 0 && incoming.length === 0 && (
            <p
              className="px-1 text-[12px]"
              style={{ color: "var(--nx-text-muted)" }}
            >
              No facts touch this entity yet.
            </p>
          )}
          {outgoing.length > 0 && (
            <ConnectionGroup
              title="Outgoing"
              direction="out"
              edges={outgoing}
              nodeById={nodeById}
              currentId={node.id}
              onPickEntity={onPickEntity}
            />
          )}
          {incoming.length > 0 && (
            <ConnectionGroup
              title="Incoming"
              direction="in"
              edges={incoming}
              nodeById={nodeById}
              currentId={node.id}
              onPickEntity={onPickEntity}
            />
          )}
        </>
      )}

      {edge && (
        <>
          <div className="space-y-1.5">
            <SectionLabel>Endpoints</SectionLabel>
            <EdgeEndpoint
              role="from"
              other={nodeById.get(edge.source)}
              onPick={() => onPickEntity(edge.source)}
            />
            <EdgeEndpoint
              role="to"
              other={nodeById.get(edge.target)}
              onPick={() => onPickEntity(edge.target)}
            />
          </div>
          {edge.valid_at && (
            <dl
              className="space-y-1 text-[12px]"
              style={{ color: "var(--nx-text-muted)" }}
            >
              <div className="flex items-baseline justify-between gap-3">
                <dt
                  className="font-semibold uppercase tracking-wider text-[9px]"
                  style={{ color: "var(--nx-text-muted)" }}
                >
                  Valid from
                </dt>
                <dd
                  className="text-right"
                  style={{ color: "var(--nx-text-secondary)" }}
                >
                  {new Date(edge.valid_at).toLocaleString()}
                </dd>
              </div>
            </dl>
          )}
        </>
      )}

      <div
        className="truncate font-mono text-[11px]"
        style={{ color: "var(--nx-text-muted)" }}
        title={node?.id ?? edge?.id}
      >
        {node?.id ?? edge?.id}
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h4
      className="px-1 text-[11px] font-semibold uppercase tracking-wider"
      style={{ color: "var(--nx-text-secondary)" }}
    >
      {children}
    </h4>
  );
}

function NexusFactsHeader({
  outgoingCount,
  incomingCount,
}: {
  outgoingCount: number;
  incomingCount: number;
}) {
  return (
    <div className="flex items-center justify-between px-1">
      <h4
        className="text-[11px] font-semibold uppercase tracking-wider"
        style={{ color: "var(--nx-text-secondary)" }}
      >
        Facts
      </h4>
      <div
        className="flex items-center gap-2 text-[11px]"
        style={{ color: "var(--nx-text-muted)" }}
      >
        <span className="inline-flex items-center gap-1">
          <ArrowRight className="h-3 w-3" />
          <span className="tabular-nums">{outgoingCount}</span>
        </span>
        <span className="inline-flex items-center gap-1">
          <ArrowLeft className="h-3 w-3" />
          <span className="tabular-nums">{incomingCount}</span>
        </span>
      </div>
    </div>
  );
}

function ConnectionGroup({
  title,
  direction,
  edges,
  nodeById,
  currentId,
  onPickEntity,
}: {
  title: string;
  direction: "out" | "in";
  edges: GraphEdge[];
  nodeById: Map<string, GraphNode>;
  currentId: string;
  onPickEntity: (id: string) => void;
}) {
  const Icon = direction === "out" ? ArrowRight : ArrowLeft;
  return (
    <section className="space-y-1.5">
      <div
        className="flex items-center gap-1.5 px-1 text-[11px] uppercase tracking-wider"
        style={{ color: "var(--nx-text-muted)" }}
      >
        <Icon className="h-3 w-3" />
        <span>{title}</span>
        <span className="ml-auto tabular-nums">{edges.length}</span>
      </div>
      <ul className="space-y-1">
        {edges.map((e) => {
          const otherId = direction === "out" ? e.target : e.source;
          const other = nodeById.get(otherId);
          if (!other || other.id === currentId) return null;
          return (
            <li key={e.id}>
              <ConnectionRow
                fact={e.fact}
                direction={direction}
                other={other}
                validAt={e.valid_at}
                onPick={() => onPickEntity(other.id)}
              />
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function ConnectionRow({
  fact,
  direction,
  other,
  validAt,
  onPick,
}: {
  fact: string;
  direction: "out" | "in";
  other: GraphNode;
  validAt: string | null;
  onPick: () => void;
}) {
  const otherColor = colorFor(other.labels[0] ?? other.kind ?? "node");
  const Icon = direction === "out" ? ArrowRight : ArrowLeft;
  return (
    <button
      type="button"
      onClick={onPick}
      className="group block w-full rounded-lg border p-2 text-left transition-colors"
      style={{
        backgroundColor: "var(--nx-elevated)",
        borderColor: "var(--nx-border-subtle)",
      }}
      onMouseEnter={(ev) => {
        const t = ev.currentTarget;
        t.style.borderColor = "var(--nx-accent)";
        t.style.backgroundColor = "var(--nx-hover)";
      }}
      onMouseLeave={(ev) => {
        const t = ev.currentTarget;
        t.style.borderColor = "var(--nx-border-subtle)";
        t.style.backgroundColor = "var(--nx-elevated)";
      }}
    >
      <div
        className="line-clamp-2 text-[12px] leading-snug"
        style={{ color: "var(--nx-text-primary)" }}
      >
        {fact}
      </div>
      <div className="mt-1.5 flex items-center gap-1.5">
        <Icon
          className="h-3 w-3 shrink-0"
          style={{ color: "var(--nx-text-muted)" }}
        />
        <span
          className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-[9px] font-semibold"
          style={{
            backgroundColor: otherColor + "33",
            color: otherColor,
          }}
          title={(other.labels[0] ?? other.kind) || "Entity"}
        >
          ●
        </span>
        <span
          className="min-w-0 flex-1 truncate text-[12px] font-medium"
          style={{ color: "var(--nx-text-primary)" }}
        >
          {other.name}
        </span>
        {validAt && (
          <span
            className="shrink-0 text-[11px] tabular-nums"
            style={{ color: "var(--nx-text-muted)" }}
            title={new Date(validAt).toLocaleString()}
          >
            {formatShort(validAt)}
          </span>
        )}
      </div>
    </button>
  );
}

function EdgeEndpoint({
  role,
  other,
  onPick,
}: {
  role: "from" | "to";
  other: GraphNode | undefined;
  onPick: () => void;
}) {
  if (!other) {
    return (
      <div
        className="rounded border p-2 text-[12px]"
        style={{
          backgroundColor: "var(--nx-elevated)",
          borderColor: "var(--nx-border-subtle)",
          color: "var(--nx-text-muted)",
        }}
      >
        {role === "from" ? "source" : "target"}: not in current view
      </div>
    );
  }
  const color = colorFor(other.labels[0] ?? other.kind ?? "node");
  return (
    <button
      type="button"
      onClick={onPick}
      className="flex w-full items-center gap-1.5 rounded border p-2 text-left transition-colors"
      style={{
        backgroundColor: "var(--nx-elevated)",
        borderColor: "var(--nx-border-subtle)",
      }}
      onMouseEnter={(ev) => {
        ev.currentTarget.style.borderColor = "var(--nx-accent)";
      }}
      onMouseLeave={(ev) => {
        ev.currentTarget.style.borderColor = "var(--nx-border-subtle)";
      }}
    >
      <span
        className="w-7 shrink-0 text-[9px] font-semibold uppercase tracking-wider"
        style={{ color: "var(--nx-text-muted)" }}
      >
        {role}
      </span>
      <span
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ background: color }}
      />
      <span
        className="min-w-0 flex-1 truncate text-[12px] font-medium"
        style={{ color: "var(--nx-text-primary)" }}
      >
        {other.name}
      </span>
    </button>
  );
}

function formatShort(iso: string): string {
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const day = 24 * 60 * 60 * 1000;
  if (diffMs < day) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  if (diffMs < 7 * day) {
    return `${Math.floor(diffMs / day)}d`;
  }
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
