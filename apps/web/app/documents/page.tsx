"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { ArrowUpRight, FileText, Loader2, RefreshCw, X } from "lucide-react";

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
import { colorFor } from "@/lib/colors";
import { fetcher } from "@/lib/api";
import type { DocumentMap as DocumentMapData, DocumentPoint } from "@/lib/types";

const DocumentMap = dynamic(() => import("./DocumentMap"), { ssr: false });

export default function DocumentsPage() {
  const [selected, setSelected] = useState<DocumentPoint | null>(null);
  const [sources, setSources] = useState<Set<string> | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRangeKey>("all");

  // No `?limit=` — API returns every document for the tenant. Filters in the
  // panel narrow client-side; that's the only place limits should come from.
  const { data, error, isLoading, mutate, isValidating } = useSWR<DocumentMapData>(
    `/api/v1/documents/vectors`,
    fetcher,
    { refreshInterval: 10000 },
  );

  const allPoints = data?.points ?? [];

  const sourceOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const p of allPoints) counts.set(p.source, (counts.get(p.source) ?? 0) + 1);
    return Array.from(counts, ([key, count]) => ({ key, count })).sort(
      (a, b) => b.count - a.count,
    );
  }, [allPoints]);

  const filtered = useMemo(() => {
    return allPoints.filter(
      (p) =>
        (sources === null || sources.has(p.source)) &&
        withinTimeRange(p.ingest_time, timeRange),
    );
  }, [allPoints, sources, timeRange]);

  const var1 = data ? Math.round((data.variance_explained[0] ?? 0) * 100) : 0;
  const var2 = data ? Math.round((data.variance_explained[1] ?? 0) * 100) : 0;

  return (
    <NexusShell
      hasSelection={!!selected}
      filters={
        <>
          <NexusSection title="Sources">
            <MultiSelectFilter
              options={sourceOptions}
              selected={sources}
              onChange={setSources}
              searchable
              emptyHint="No documents ingested yet."
            />
          </NexusSection>
          <NexusDivider />
          <NexusSection
            title="Time"
            hint={
              <>
                Filter by <code>ingest_time</code>.
              </>
            }
          >
            <TimeRangeFilter value={timeRange} onChange={setTimeRange} />
          </NexusSection>
        </>
      }
      inspector={selected ? <DocInspector selected={selected} onClear={() => setSelected(null)} /> : null}
      toolbar={
        <NexusToolbar>
          <button
            type="button"
            onClick={() => mutate()}
            disabled={isValidating}
            className="flex items-center gap-1.5 rounded px-2 py-1 text-[12px] transition-colors disabled:opacity-50"
            style={{ color: "var(--nx-text-secondary)" }}
            onMouseEnter={(e) =>
              ((e.currentTarget as HTMLButtonElement).style.color =
                "var(--nx-text-primary)")
            }
            onMouseLeave={(e) =>
              ((e.currentTarget as HTMLButtonElement).style.color =
                "var(--nx-text-secondary)")
            }
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
              {filtered.length} / {allPoints.length} docs
            </span>
          )}
        </NexusToolbar>
      }
      statusLeft={
        <>
          <span>
            <span style={{ color: "var(--nx-text-primary)" }} className="tabular-nums">
              {filtered.length}
            </span>{" "}
            / <span className="tabular-nums">{allPoints.length}</span> docs visible
          </span>
          <span style={{ color: "var(--nx-border-default)" }}>·</span>
          <span>
            {sources === null
              ? "All sources"
              : `${sources.size}/${sourceOptions.length} sources`}
          </span>
          <span style={{ color: "var(--nx-border-default)" }}>·</span>
          <span>{timeRange === "all" ? "All time" : timeRange}</span>
        </>
      }
      statusRight={
        data && allPoints.length > 0 ? (
          <span>
            PC1 {var1}% · PC2 {var2}%
          </span>
        ) : null
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
      {data && allPoints.length === 0 && (
        <div
          className="absolute inset-0 grid place-items-center px-6 text-center text-sm"
          style={{ color: "var(--nx-text-muted)" }}
        >
          No embedded documents yet. Ingest something via{" "}
          <Link
            href="/ingest"
            className="ml-1 underline"
            style={{ color: "var(--nx-accent)" }}
          >
            /ingest
          </Link>
          .
        </div>
      )}
      {data && allPoints.length > 0 && filtered.length === 0 && (
        <div
          className="absolute inset-0 grid place-items-center px-6 text-center text-sm"
          style={{ color: "var(--nx-text-muted)" }}
        >
          No documents match the current filters.
        </div>
      )}
      {data && filtered.length > 0 && (
        <DocumentMap
          points={filtered}
          selectedId={selected?.event_id ?? null}
          onSelect={(p) => setSelected(p)}
          varianceExplained={data.variance_explained as [number, number]}
        />
      )}
    </NexusShell>
  );
}

function DocInspector({
  selected,
  onClear,
}: {
  selected: DocumentPoint;
  onClear: () => void;
}) {
  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-start gap-2">
        <span
          className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded"
          style={{ backgroundColor: colorFor(selected.source) + "33" }}
        >
          <FileText
            className="h-3 w-3"
            style={{ color: colorFor(selected.source) }}
          />
        </span>
        <div className="min-w-0 flex-1">
          <div
            className="break-words text-xs font-semibold"
            style={{ color: "var(--nx-text-primary)" }}
          >
            {selected.subject}
          </div>
          <div
            className="truncate font-mono text-[11px]"
            style={{ color: "var(--nx-text-muted)" }}
          >
            {selected.event_id}
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

      <div className="flex flex-wrap gap-1">
        <Chip color={colorFor(selected.source)}>{selected.source}</Chip>
        <Chip>{selected.type}</Chip>
      </div>

      {selected.text_preview && (
        <div
          className="rounded border p-2 text-[12px] leading-relaxed whitespace-pre-wrap"
          style={{
            backgroundColor: "var(--nx-elevated)",
            borderColor: "var(--nx-border-subtle)",
            color: "var(--nx-text-secondary)",
          }}
        >
          {selected.text_preview.length > 600
            ? selected.text_preview.slice(0, 600) + "…"
            : selected.text_preview}
        </div>
      )}

      <dl
        className="space-y-1 text-[12px]"
        style={{ color: "var(--nx-text-muted)" }}
      >
        <Row label="Ingested">
          {new Date(selected.ingest_time).toLocaleString()}
        </Row>
        {selected.event_time && (
          <Row label="Event time">
            {new Date(selected.event_time).toLocaleString()}
          </Row>
        )}
        <Row label="Coords">
          ({selected.x.toFixed(2)}, {selected.y.toFixed(2)})
        </Row>
      </dl>

      <Link
        href={`/events/${encodeURIComponent(selected.event_id)}`}
        className="inline-flex items-center gap-1 text-[12px] underline"
        style={{ color: "var(--nx-accent)" }}
      >
        Open event <ArrowUpRight className="h-3 w-3" />
      </Link>
    </div>
  );
}

function Chip({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      className="rounded px-1.5 py-0.5 font-mono text-[11px]"
      style={{
        backgroundColor: color ? color + "22" : "var(--nx-elevated)",
        color: color ?? "var(--nx-text-secondary)",
      }}
    >
      {children}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt
        className="font-semibold uppercase tracking-wider text-[9px]"
        style={{ color: "var(--nx-text-muted)" }}
      >
        {label}
      </dt>
      <dd className="text-right" style={{ color: "var(--nx-text-secondary)" }}>
        {children}
      </dd>
    </div>
  );
}
