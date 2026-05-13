"use client";

import * as React from "react";
import { Search } from "lucide-react";

import { colorFor } from "@/lib/colors";
import { cn } from "@/lib/utils";

// ── Source / label multi-select (GitNexus-style row buttons) ────────────────

export function MultiSelectFilter({
  options,
  selected,
  onChange,
  searchable = false,
  emptyHint = "Nothing to filter yet.",
  colored = true,
}: {
  options: { key: string; count: number }[];
  /** null = "all selected" (no filter); Set = active selection. */
  selected: Set<string> | null;
  onChange: (next: Set<string> | null) => void;
  searchable?: boolean;
  emptyHint?: string;
  colored?: boolean;
}) {
  const [query, setQuery] = React.useState("");
  const filtered = React.useMemo(() => {
    if (!query) return options;
    const q = query.toLowerCase();
    return options.filter((o) => o.key.toLowerCase().includes(q));
  }, [options, query]);

  const allSelected = selected === null;
  const noneSelected = selected !== null && selected.size === 0;

  function isActive(key: string): boolean {
    return allSelected || (selected !== null && selected.has(key));
  }

  function toggle(key: string) {
    if (allSelected) {
      const next = new Set(options.map((o) => o.key));
      next.delete(key);
      onChange(next);
      return;
    }
    const next = new Set(selected!);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }

  return (
    <div className="space-y-1.5">
      {searchable && options.length > 6 && (
        <div className="relative">
          <Search
            className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2"
            style={{ color: "var(--nx-text-muted)" }}
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search…"
            className="w-full rounded border py-1.5 pl-7 pr-2 text-[12px] outline-none transition-colors focus:border-[var(--nx-accent)]"
            style={{
              backgroundColor: "var(--nx-elevated)",
              borderColor: "var(--nx-border-subtle)",
              color: "var(--nx-text-primary)",
            }}
          />
        </div>
      )}

      <div
        className="flex items-center gap-2 px-1 text-[11px]"
        style={{ color: "var(--nx-text-muted)" }}
      >
        <button
          type="button"
          onClick={() => onChange(null)}
          className={cn(
            "transition-colors hover:text-[var(--nx-text-primary)]",
            allSelected && "font-medium",
          )}
          style={allSelected ? { color: "var(--nx-text-primary)" } : undefined}
        >
          All
        </button>
        <span>·</span>
        <button
          type="button"
          onClick={() => onChange(new Set())}
          className={cn(
            "transition-colors hover:text-[var(--nx-text-primary)]",
            noneSelected && "font-medium",
          )}
          style={noneSelected ? { color: "var(--nx-text-primary)" } : undefined}
        >
          None
        </button>
        <span className="ml-auto tabular-nums">{options.length}</span>
      </div>

      {options.length === 0 ? (
        <p
          className="px-1 py-1 text-xs"
          style={{ color: "var(--nx-text-muted)" }}
        >
          {emptyHint}
        </p>
      ) : (
        <ul className="space-y-0.5">
          {filtered.map((opt) => {
            const active = isActive(opt.key);
            return (
              <li key={opt.key}>
                <button
                  type="button"
                  onClick={() => toggle(opt.key)}
                  className="flex w-full items-center gap-2.5 rounded px-1.5 py-1 text-left transition-colors"
                  style={{
                    backgroundColor: active ? "var(--nx-elevated)" : "transparent",
                    color: active
                      ? "var(--nx-text-primary)"
                      : "var(--nx-text-muted)",
                  }}
                  onMouseEnter={(e) => {
                    if (!active)
                      e.currentTarget.style.backgroundColor = "var(--nx-hover)";
                  }}
                  onMouseLeave={(e) => {
                    if (!active)
                      e.currentTarget.style.backgroundColor = "transparent";
                  }}
                >
                  {colored && (
                    <span
                      className="flex h-4 w-4 shrink-0 items-center justify-center rounded"
                      style={{
                        backgroundColor: colorFor(opt.key) + "33",
                      }}
                    >
                      <span
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ backgroundColor: colorFor(opt.key) }}
                      />
                    </span>
                  )}
                  <code className="flex-1 truncate font-mono text-[12px]">
                    {opt.key}
                  </code>
                  <span
                    className="tabular-nums text-[11px]"
                    style={{ color: "var(--nx-text-muted)" }}
                  >
                    {opt.count}
                  </span>
                  <span
                    className="h-1.5 w-1.5 shrink-0 rounded-full transition-colors"
                    style={{
                      backgroundColor: active
                        ? "var(--nx-accent)"
                        : "var(--nx-border-subtle)",
                    }}
                  />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── Time range preset (GitNexus-style chips) ────────────────────────────────

export type TimeRangeKey = "1h" | "24h" | "7d" | "30d" | "all";

export const TIME_RANGE_OPTIONS: { key: TimeRangeKey; label: string; ms: number | null }[] = [
  { key: "1h", label: "1h", ms: 60 * 60 * 1000 },
  { key: "24h", label: "24h", ms: 24 * 60 * 60 * 1000 },
  { key: "7d", label: "7d", ms: 7 * 24 * 60 * 60 * 1000 },
  { key: "30d", label: "30d", ms: 30 * 24 * 60 * 60 * 1000 },
  { key: "all", label: "All", ms: null },
];

export function TimeRangeFilter({
  value,
  onChange,
}: {
  value: TimeRangeKey;
  onChange: (next: TimeRangeKey) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {TIME_RANGE_OPTIONS.map((opt) => {
        const active = value === opt.key;
        return (
          <button
            key={opt.key}
            type="button"
            onClick={() => onChange(opt.key)}
            className="rounded px-2 py-1 text-[12px] transition-colors"
            style={
              active
                ? {
                    backgroundColor: "var(--nx-accent)",
                    color: "#fff",
                  }
                : {
                    backgroundColor: "var(--nx-elevated)",
                    color: "var(--nx-text-secondary)",
                  }
            }
            onMouseEnter={(e) => {
              if (!active)
                e.currentTarget.style.backgroundColor = "var(--nx-hover)";
            }}
            onMouseLeave={(e) => {
              if (!active)
                e.currentTarget.style.backgroundColor = "var(--nx-elevated)";
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function withinTimeRange(iso: string | null | undefined, key: TimeRangeKey): boolean {
  if (!iso) return key === "all";
  const opt = TIME_RANGE_OPTIONS.find((o) => o.key === key);
  if (!opt || opt.ms === null) return true;
  return Date.now() - new Date(iso).getTime() <= opt.ms;
}
