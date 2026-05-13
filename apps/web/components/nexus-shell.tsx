"use client";

import * as React from "react";
import {
  Filter,
  MousePointerClick,
  PanelLeft,
  PanelLeftClose,
} from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * NexusShell — GitNexus-style three-strip layout:
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ header (logo · view tabs · counts)                           │
 *   ├──────────┬───────────────────────────────────────────────────┤
 *   │          │                                                   │
 *   │  left    │  canvas (full-bleed)                              │
 *   │  rail    │                                                   │
 *   │  Filters │  ┌────────────┐                                   │
 *   │  / Insp. │  │ floating   │                                   │
 *   │          │  │ toolbar    │                                   │
 *   │          │  └────────────┘                                   │
 *   │  stats   │                                                   │
 *   ├──────────┴───────────────────────────────────────────────────┤
 *   │ status bar                                                   │
 *   └──────────────────────────────────────────────────────────────┘
 *
 * - Rail collapses to a vertical w-12 icon stack (Filters / Inspector).
 * - On selection, the rail auto-switches to the Inspector tab.
 * - Right-side overlays do NOT exist in this shell — selection details
 *   live on the LEFT, matching GitNexus's CodeReferencesPanel pattern.
 */

export type NexusTab = "filters" | "inspector";

export function NexusShell({
  filters,
  inspector,
  hasSelection = false,
  toolbar,
  statusLeft,
  statusRight,
  children,
}: {
  /** Filter section content (rendered inside Filters tab). */
  filters: React.ReactNode;
  /** Selection-details content (rendered inside Inspector tab). */
  inspector?: React.ReactNode;
  /** When true, auto-switch the rail to Inspector and show a "selected" indicator. */
  hasSelection?: boolean;
  /** Floating toolbar inside the canvas (top-left). */
  toolbar?: React.ReactNode;
  /** Left side of the bottom status bar. */
  statusLeft?: React.ReactNode;
  /** Right side of the bottom status bar. */
  statusRight?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [tab, setTab] = React.useState<NexusTab>("filters");
  const [collapsed, setCollapsed] = React.useState(false);
  const [width, setWidth] = React.useState<number>(DEFAULT_RAIL_WIDTH);

  // Hydrate width from localStorage after mount.
  React.useEffect(() => {
    try {
      const raw = window.localStorage.getItem(RAIL_WIDTH_KEY);
      const v = raw ? parseInt(raw, 10) : NaN;
      if (Number.isFinite(v)) {
        setWidth(Math.max(MIN_RAIL_WIDTH, Math.min(MAX_RAIL_WIDTH, v)));
      }
    } catch {
      /* ignore */
    }
  }, []);

  React.useEffect(() => {
    try {
      window.localStorage.setItem(RAIL_WIDTH_KEY, String(width));
    } catch {
      /* ignore */
    }
  }, [width]);

  // When a selection arrives, switch focus to the inspector tab so the user
  // sees the details immediately (and expand the rail if it was collapsed).
  const prevSelection = React.useRef(false);
  React.useEffect(() => {
    if (hasSelection && !prevSelection.current) {
      setTab("inspector");
      setCollapsed(false);
    }
    prevSelection.current = hasSelection;
  }, [hasSelection]);

  return (
    <div
      className="nexus flex flex-col"
      style={{ height: "calc(100vh - 3.5rem)" }}
    >
      {/* Main: left rail + canvas (the app's top topbar already handles
          branding + breadcrumb, so no inner header here) */}
      <div className="flex min-h-0 flex-1">
        <LeftRail
          tab={tab}
          setTab={setTab}
          collapsed={collapsed}
          setCollapsed={setCollapsed}
          width={width}
          setWidth={setWidth}
          filters={filters}
          inspector={inspector}
          inspectorBadge={hasSelection}
        />

        <div
          className="relative min-w-0 flex-1 overflow-hidden"
          style={{ backgroundColor: "var(--nx-void)" }}
        >
          {toolbar && (
            <div className="absolute top-3 left-3 z-20 flex items-center gap-2">
              {toolbar}
            </div>
          )}
          {children}
        </div>
      </div>

      {/* Status bar */}
      <footer
        className="flex h-7 shrink-0 items-center justify-between border-t border-dashed px-4 text-[11px]"
        style={{
          backgroundColor: "var(--nx-deep)",
          borderColor: "var(--nx-border-subtle)",
          color: "var(--nx-text-muted)",
        }}
      >
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: "#10b981" }}
            />
            <span>Ready</span>
          </div>
          {statusLeft && (
            <>
              <span style={{ color: "var(--nx-border-default)" }}>·</span>
              {statusLeft}
            </>
          )}
        </div>
        <div>{statusRight}</div>
      </footer>
    </div>
  );
}

// ── Left rail ───────────────────────────────────────────────────────────────

const DEFAULT_RAIL_WIDTH = 340;
const MIN_RAIL_WIDTH = 260;
const MAX_RAIL_WIDTH = 560;
const RAIL_WIDTH_KEY = "meaninggrid.nexus.railWidth";

function LeftRail({
  tab,
  setTab,
  collapsed,
  setCollapsed,
  width,
  setWidth,
  filters,
  inspector,
  inspectorBadge,
}: {
  tab: NexusTab;
  setTab: (t: NexusTab) => void;
  collapsed: boolean;
  setCollapsed: (b: boolean) => void;
  width: number;
  setWidth: (n: number) => void;
  filters: React.ReactNode;
  inspector: React.ReactNode | undefined;
  inspectorBadge: boolean;
}) {
  const dragRef = React.useRef<{ startX: number; startWidth: number } | null>(
    null,
  );

  const startResize = React.useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startWidth: width };
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      const onMove = (ev: MouseEvent) => {
        const s = dragRef.current;
        if (!s) return;
        const delta = ev.clientX - s.startX;
        const next = Math.max(
          MIN_RAIL_WIDTH,
          Math.min(MAX_RAIL_WIDTH, s.startWidth + delta),
        );
        setWidth(next);
      };
      const onUp = () => {
        dragRef.current = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [width, setWidth],
  );

  if (collapsed) {
    return (
      <aside
        className="flex w-12 shrink-0 flex-col items-center gap-2 border-r py-3"
        style={{
          backgroundColor: "var(--nx-surface)",
          borderColor: "var(--nx-border-subtle)",
        }}
      >
        <RailIconButton
          title="Expand panel"
          onClick={() => setCollapsed(false)}
        >
          <PanelLeft className="h-4 w-4" />
        </RailIconButton>
        <div
          className="my-1 h-px w-6"
          style={{ backgroundColor: "var(--nx-border-subtle)" }}
        />
        <RailIconButton
          title="Filters"
          active={tab === "filters"}
          onClick={() => {
            setCollapsed(false);
            setTab("filters");
          }}
        >
          <Filter className="h-4 w-4" />
        </RailIconButton>
        {inspector && (
          <RailIconButton
            title="Inspector"
            active={tab === "inspector"}
            highlight={inspectorBadge}
            onClick={() => {
              setCollapsed(false);
              setTab("inspector");
            }}
          >
            <MousePointerClick className="h-4 w-4" />
          </RailIconButton>
        )}
      </aside>
    );
  }

  return (
    <aside
      className="nx-animate-slide-in relative flex shrink-0 flex-col border-r text-[13px]"
      style={{
        width,
        backgroundColor: "var(--nx-surface)",
        borderColor: "var(--nx-border-subtle)",
      }}
    >
      <div
        className="flex h-10 shrink-0 items-center justify-between border-b px-2"
        style={{ borderColor: "var(--nx-border-subtle)" }}
      >
        <div className="flex items-center gap-1">
          <TabPill active={tab === "filters"} onClick={() => setTab("filters")}>
            Filters
          </TabPill>
          {inspector && (
            <TabPill
              active={tab === "inspector"}
              onClick={() => setTab("inspector")}
              dot={inspectorBadge}
            >
              Inspector
            </TabPill>
          )}
        </div>
        <RailIconButton title="Collapse panel" onClick={() => setCollapsed(true)}>
          <PanelLeftClose className="h-4 w-4" />
        </RailIconButton>
      </div>

      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-3.5 space-y-4">
        {tab === "filters" && filters}
        {tab === "inspector" &&
          (inspector ?? (
            <p
              className="px-1 text-[12px]"
              style={{ color: "var(--nx-text-muted)" }}
            >
              Click a node or document to inspect it.
            </p>
          ))}
      </div>

      {/* Drag handle — sits on top of the right border for col-resize. */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panel"
        onMouseDown={startResize}
        onDoubleClick={() => setWidth(DEFAULT_RAIL_WIDTH)}
        className="absolute top-0 -right-1 z-10 h-full w-2 cursor-col-resize transition-colors"
        style={{ backgroundColor: "transparent" }}
        onMouseEnter={(e) =>
          (e.currentTarget.style.backgroundColor = "rgba(124, 58, 237, 0.35)")
        }
        onMouseLeave={(e) =>
          (e.currentTarget.style.backgroundColor = "transparent")
        }
      />
    </aside>
  );
}

function TabPill({
  active,
  dot,
  children,
  onClick,
}: {
  active: boolean;
  dot?: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative rounded px-2.5 py-1 text-[13px] font-medium transition-colors",
      )}
      style={
        active
          ? {
              backgroundColor: "rgba(124, 58, 237, 0.18)",
              color: "var(--nx-accent)",
            }
          : { color: "var(--nx-text-secondary)" }
      }
    >
      {children}
      {dot && (
        <span
          className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: "#f59e0b" }}
        />
      )}
    </button>
  );
}

function RailIconButton({
  title,
  active,
  highlight,
  onClick,
  children,
}: {
  title: string;
  active?: boolean;
  highlight?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className="relative rounded p-1.5 transition-colors"
      style={
        active
          ? {
              backgroundColor: "rgba(124, 58, 237, 0.18)",
              color: "var(--nx-accent)",
            }
          : { color: "var(--nx-text-secondary)" }
      }
    >
      {children}
      {highlight && !active && (
        <span
          className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: "#f59e0b" }}
        />
      )}
    </button>
  );
}

// ── Filter section heading (shared) ──────────────────────────────────────────

export function NexusSection({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <h3
        className="px-1 text-[11px] font-semibold uppercase tracking-wider"
        style={{ color: "var(--nx-text-secondary)" }}
      >
        {title}
      </h3>
      {hint && (
        <p
          className="px-1 text-[12px]"
          style={{ color: "var(--nx-text-muted)" }}
        >
          {hint}
        </p>
      )}
      {children}
    </section>
  );
}

export function NexusToolbar({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div
      className="flex items-center gap-2 rounded-lg border px-2 py-1.5 backdrop-blur"
      style={{
        backgroundColor: "rgba(16, 16, 24, 0.85)",
        borderColor: "var(--nx-border-subtle)",
      }}
    >
      {children}
    </div>
  );
}

export function NexusDivider() {
  return (
    <div
      className="h-px w-full"
      style={{ backgroundColor: "var(--nx-border-subtle)" }}
    />
  );
}
