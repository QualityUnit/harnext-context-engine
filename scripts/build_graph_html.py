# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Export the live /graph view to a single self-contained HTML file.

Pulls the JSON from `GET /api/v1/graph` (or a local file via --file) and
inlines it into a template that mirrors apps/web/app/graph at runtime:
the same fcose layout, dark theme, left rail (Filters + Inspector),
floating toolbar, status bar, focus mode, and hover label.

Usage:
    uv run scripts/build_graph_html.py
    uv run scripts/build_graph_html.py --url http://localhost:8000/api/v1/graph
    uv run scripts/build_graph_html.py --file /tmp/graph.json --out exports/graph.html
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

TEMPLATE = r"""<!doctype html>
<html lang="en" class="dark">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>MeaningGrid — Graph</title>

<script src="https://cdn.jsdelivr.net/npm/cytoscape@3.30.0/dist/cytoscape.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/layout-base@2.0.1/layout-base.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cose-base@2.2.0/cose-base.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-fcose@2.2.0/cytoscape-fcose.js"></script>

<style>
  /* ── theme tokens (mirrors apps/web/app/globals.css .nexus scope) ─────── */
  :root {
    --nx-void:           #06060a;
    --nx-deep:           #0a0a10;
    --nx-surface:        #101018;
    --nx-elevated:       #16161f;
    --nx-hover:          #1c1c28;
    --nx-border-subtle:  #1e1e2a;
    --nx-border-default: #2a2a3a;
    --nx-text-primary:   #e4e4ed;
    --nx-text-secondary: #8888a0;
    --nx-text-muted:     #5a5a70;
    --nx-accent:         #7c3aed;
    --nx-accent-dim:     #5b21b6;
    --nx-accent-light:   #a78bfa;
  }

  *, *::before, *::after { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; height: 100%;
    background: var(--nx-void); color: var(--nx-text-primary);
    font-family: "Outfit", ui-sans-serif, system-ui, sans-serif;
    font-size: 14px;
    overflow: hidden;
  }
  code, .mono { font-family: "JetBrains Mono", "Fira Code", ui-monospace, monospace; }

  /* ── three-strip shell ────────────────────────────────────────────────── */
  .nexus { display: flex; flex-direction: column; height: 100vh; }
  .nexus-main { display: flex; flex: 1 1 0; min-height: 0; }
  .canvas {
    position: relative; flex: 1 1 0; min-width: 0; overflow: hidden;
    background: var(--nx-void);
  }
  #cy { width: 100%; height: 100%;
    background-color: var(--nx-void);
    background-image: radial-gradient(circle at 1px 1px, rgba(255,255,255,0.04) 1px, transparent 0);
    background-size: 24px 24px;
  }

  /* ── status bar ───────────────────────────────────────────────────────── */
  .statusbar {
    display: flex; align-items: center; justify-content: space-between;
    height: 28px; padding: 0 16px; font-size: 11px;
    background: var(--nx-deep); color: var(--nx-text-muted);
    border-top: 1px dashed var(--nx-border-subtle);
    flex-shrink: 0;
  }
  .statusbar .left, .statusbar .right { display: flex; align-items: center; gap: 12px; }
  .dot-ok { display:inline-block; height:6px; width:6px; border-radius:9999px; background:#10b981; margin-right:6px; }
  .sep { color: var(--nx-border-default); }
  .tabular-nums { font-variant-numeric: tabular-nums; }

  /* ── left rail ────────────────────────────────────────────────────────── */
  .rail {
    width: 340px; flex-shrink: 0; display: flex; flex-direction: column;
    background: var(--nx-surface); border-right: 1px solid var(--nx-border-subtle);
    font-size: 13px;
  }
  .rail-tabs {
    display: flex; align-items: center; justify-content: space-between;
    height: 40px; padding: 0 8px;
    border-bottom: 1px solid var(--nx-border-subtle);
  }
  .tab-pill {
    background: transparent; border: 0; cursor: pointer;
    padding: 4px 10px; border-radius: 4px;
    font-size: 13px; font-weight: 500;
    color: var(--nx-text-secondary);
    transition: background-color .15s, color .15s;
    position: relative;
  }
  .tab-pill.active { background: rgba(124,58,237,.18); color: var(--nx-accent); }
  .tab-pill .dot {
    position: absolute; top: -2px; right: -2px;
    width: 6px; height: 6px; border-radius: 9999px; background: #f59e0b;
  }
  .icon-btn {
    background: transparent; border: 0; cursor: pointer;
    padding: 6px; border-radius: 4px;
    color: var(--nx-text-secondary);
    display: inline-flex; align-items: center; justify-content: center;
  }
  .icon-btn:hover { background: var(--nx-hover); }
  .icon-btn.active { background: rgba(124,58,237,.18); color: var(--nx-accent); }

  .rail-body {
    min-height: 0; flex: 1 1 0; overflow-y: auto;
    padding: 14px;
  }
  .rail-body > * + * { margin-top: 16px; }
  /* scrollbar styling */
  .rail-body::-webkit-scrollbar { width: 8px; }
  .rail-body::-webkit-scrollbar-track { background: var(--nx-deep); }
  .rail-body::-webkit-scrollbar-thumb { background: var(--nx-border-default); border-radius: 4px; }

  /* ── section ──────────────────────────────────────────────────────────── */
  .section { display: flex; flex-direction: column; gap: 8px; }
  .section-title {
    padding: 0 4px;
    font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .08em;
    color: var(--nx-text-secondary);
    margin: 0;
  }
  .section-hint {
    padding: 0 4px; font-size: 12px; color: var(--nx-text-muted); margin: 0;
  }
  .divider { height: 1px; width: 100%; background: var(--nx-border-subtle); }

  /* ── multi-select filter ──────────────────────────────────────────────── */
  .ms { display: flex; flex-direction: column; gap: 6px; }
  .ms .search-wrap { position: relative; }
  .ms .search-wrap input {
    width: 100%; padding: 6px 8px 6px 28px; font-size: 12px;
    background: var(--nx-elevated); color: var(--nx-text-primary);
    border: 1px solid var(--nx-border-subtle); border-radius: 4px;
    outline: none;
  }
  .ms .search-wrap input:focus { border-color: var(--nx-accent); }
  .ms .search-wrap .icon {
    position: absolute; left: 8px; top: 50%; transform: translateY(-50%);
    color: var(--nx-text-muted);
  }
  .ms .head { display: flex; align-items: center; gap: 8px; padding: 0 4px;
    font-size: 11px; color: var(--nx-text-muted); }
  .ms .head .link { background: none; border: 0; cursor: pointer; color: inherit; padding: 0; }
  .ms .head .link:hover { color: var(--nx-text-primary); }
  .ms .head .link.active { color: var(--nx-text-primary); font-weight: 500; }
  .ms .head .count { margin-left: auto; font-variant-numeric: tabular-nums; }
  .ms ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
  .ms .row {
    width: 100%; display: flex; align-items: center; gap: 10px;
    padding: 4px 6px; border-radius: 4px; background: transparent;
    color: var(--nx-text-muted);
    border: 0; cursor: pointer; text-align: left;
    transition: background-color .15s, color .15s;
  }
  .ms .row.active { background: var(--nx-elevated); color: var(--nx-text-primary); }
  .ms .row:hover:not(.active) { background: var(--nx-hover); }
  .ms .swatch {
    height: 16px; width: 16px; border-radius: 4px;
    display: inline-flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  .ms .swatch-dot { height: 6px; width: 6px; border-radius: 9999px; }
  .ms .row code { flex: 1 1 auto; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ms .row .count { font-size: 11px; color: var(--nx-text-muted); font-variant-numeric: tabular-nums; }
  .ms .row .pin { height: 6px; width: 6px; border-radius: 9999px; background: var(--nx-border-subtle); flex-shrink: 0; }
  .ms .row.active .pin { background: var(--nx-accent); }

  /* ── time range chips ─────────────────────────────────────────────────── */
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip {
    background: var(--nx-elevated); color: var(--nx-text-secondary);
    border: 0; cursor: pointer; padding: 4px 8px; border-radius: 4px;
    font-size: 12px;
    transition: background-color .15s, color .15s;
  }
  .chip:hover:not(.active) { background: var(--nx-hover); }
  .chip.active { background: var(--nx-accent); color: #fff; }

  /* ── toolbar (top-left of canvas) ─────────────────────────────────────── */
  .toolbar {
    position: absolute; top: 12px; left: 12px; z-index: 20;
    display: flex; align-items: center; gap: 8px;
    padding: 6px 8px;
    background: rgba(16,16,24,.85); backdrop-filter: blur(8px);
    border: 1px solid var(--nx-border-subtle); border-radius: 8px;
    font-size: 12px;
  }
  .toolbar .count { color: var(--nx-text-secondary); font-variant-numeric: tabular-nums; }

  /* ── hover label tooltip ──────────────────────────────────────────────── */
  .hover-label {
    position: absolute; bottom: 12px; left: 12px; z-index: 10;
    max-width: 32rem;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    background: rgba(16,16,24,.92); backdrop-filter: blur(8px);
    border: 1px solid var(--nx-border-subtle); border-radius: 4px;
    color: var(--nx-text-primary);
    padding: 4px 8px; font-family: "JetBrains Mono", monospace; font-size: 11px;
    display: none;
    pointer-events: none;
  }

  /* ── inspector pieces ─────────────────────────────────────────────────── */
  .inspector { display: flex; flex-direction: column; gap: 12px; font-size: 14px; }
  .insp-head { display: flex; align-items: flex-start; gap: 8px; }
  .insp-head .title-block { min-width: 0; flex: 1 1 auto; }
  .insp-eyebrow { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; color: var(--nx-text-muted); }
  .insp-title { margin-top: 4px; font-size: 12px; font-weight: 600; color: var(--nx-text-primary); word-break: break-word; }
  .insp-summary {
    border: 1px solid var(--nx-border-subtle); border-radius: 4px;
    background: var(--nx-elevated); color: var(--nx-text-secondary);
    padding: 8px; font-size: 12px; line-height: 1.6;
    white-space: pre-wrap;
  }
  .insp-labels { display: flex; flex-wrap: wrap; gap: 4px; }
  .insp-label { padding: 2px 6px; border-radius: 4px; font-size: 11px; }
  .insp-id { font-family: "JetBrains Mono", monospace; font-size: 11px; color: var(--nx-text-muted);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .facts-header { display: flex; align-items: center; justify-content: space-between; padding: 0 4px; }
  .facts-header h4 { margin: 0; font-size: 11px; font-weight: 600; letter-spacing: .08em; color: var(--nx-text-secondary); text-transform: uppercase; }
  .facts-header .nums { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--nx-text-muted); }
  .facts-header .nums .item { display: inline-flex; align-items: center; gap: 4px; }

  .conn-group { display: flex; flex-direction: column; gap: 6px; }
  .conn-group-head {
    display: flex; align-items: center; gap: 6px; padding: 0 4px;
    font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--nx-text-muted);
  }
  .conn-group-head .nums { margin-left: auto; font-variant-numeric: tabular-nums; }
  .conn-group ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .conn-row {
    display: block; width: 100%; text-align: left;
    border: 1px solid var(--nx-border-subtle); border-radius: 8px;
    background: var(--nx-elevated); cursor: pointer; padding: 8px;
    transition: background-color .15s, border-color .15s;
  }
  .conn-row:hover { background: var(--nx-hover); border-color: var(--nx-accent); }
  .conn-row .fact { font-size: 12px; line-height: 1.4; color: var(--nx-text-primary);
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .conn-row .meta { margin-top: 6px; display: flex; align-items: center; gap: 6px; }
  .conn-row .meta .dot {
    height: 16px; width: 16px; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center;
    font-size: 9px; font-weight: 600; flex-shrink: 0;
  }
  .conn-row .meta .name { flex: 1 1 auto; min-width: 0; font-size: 12px; font-weight: 500;
    color: var(--nx-text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .conn-row .meta .when { font-size: 11px; color: var(--nx-text-muted); font-variant-numeric: tabular-nums; flex-shrink: 0; }
  .conn-row .arrow { color: var(--nx-text-muted); flex-shrink: 0; }

  .endpoint {
    display: flex; align-items: center; gap: 6px;
    border: 1px solid var(--nx-border-subtle); border-radius: 4px;
    background: var(--nx-elevated); cursor: pointer; padding: 8px;
    transition: border-color .15s;
  }
  .endpoint:hover { border-color: var(--nx-accent); }
  .endpoint .role { width: 28px; flex-shrink: 0; font-size: 9px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .08em; color: var(--nx-text-muted); }
  .endpoint .pip { height: 8px; width: 8px; border-radius: 9999px; flex-shrink: 0; }
  .endpoint .name { min-width: 0; flex: 1 1 auto; font-size: 12px; font-weight: 500;
    color: var(--nx-text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* empty/loading states */
  .empty-state { position: absolute; inset: 0; display: grid; place-items: center;
    padding: 24px; text-align: center; font-size: 14px; color: var(--nx-text-muted); }
</style>
</head>
<body>

<div class="nexus">
  <div class="nexus-main">

    <!-- LEFT RAIL -->
    <aside class="rail" id="rail">
      <div class="rail-tabs">
        <div style="display:flex;align-items:center;gap:4px;">
          <button class="tab-pill active" data-tab="filters" onclick="setTab('filters')">Filters</button>
          <button class="tab-pill" data-tab="inspector" onclick="setTab('inspector')">
            Inspector
            <span class="dot" id="inspector-dot" style="display:none"></span>
          </button>
        </div>
        <button class="icon-btn" title="Collapse panel" onclick="toggleRail()" id="collapse-btn">
          <!-- panel-left-close -->
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/></svg>
        </button>
      </div>
      <div class="rail-body" id="rail-body"></div>
    </aside>

    <!-- CANVAS -->
    <div class="canvas">
      <div class="toolbar">
        <span class="count" id="toolbar-count">… / … nodes · … / … edges</span>
      </div>
      <div id="cy"></div>
      <div id="hover-label" class="hover-label"></div>
      <div id="empty" class="empty-state" style="display:none">No nodes match the current filters.</div>
    </div>

  </div>

  <!-- STATUS BAR -->
  <footer class="statusbar">
    <div class="left">
      <span><span class="dot-ok"></span>Ready</span>
      <span class="sep">·</span>
      <span><span id="status-vn" class="tabular-nums" style="color:var(--nx-text-primary)">…</span> / <span id="status-tn" class="tabular-nums">…</span> nodes</span>
      <span class="sep">·</span>
      <span><span id="status-ve" class="tabular-nums" style="color:var(--nx-text-primary)">…</span> / <span id="status-te" class="tabular-nums">…</span> edges</span>
      <span class="sep">·</span>
      <span id="status-labels">All labels</span>
      <span class="sep">·</span>
      <span id="status-time">All time</span>
    </div>
    <div class="right"></div>
  </footer>
</div>

<script id="graph-data" type="application/json">__GRAPH_DATA__</script>

<script>
/* ─────────────────────────────────────────────────────────────────────────
   1. Theme + color hash (matches apps/web/lib/colors.ts)
───────────────────────────────────────────────────────────────────────── */
const NX = {
  void: "#06060a", textOutline: "#06060a", textPrimary: "#e4e4ed",
  edge: "#2a2a3a", accent: "#7c3aed", accentLight: "#a78bfa",
};
const PALETTE = ["#6366f1","#10b981","#f59e0b","#ef4444","#06b6d4","#a855f7","#ec4899","#14b8a6","#f97316","#84cc16"];
function colorFor(key) {
  let h = 0; const s = String(key ?? "");
  for (let i = 0; i < s.length; i++) h = ((h * 31) + s.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

/* ─────────────────────────────────────────────────────────────────────────
   2. Inline lucide icons (one fn per icon — same strokes / shapes)
───────────────────────────────────────────────────────────────────────── */
function ic(name) {
  const C = {
    "arrow-right": `<polyline points="9 18 15 12 9 6"/>`,
    "arrow-left": `<polyline points="15 18 9 12 15 6"/>`,
    "x": `<path d="M18 6 6 18"/><path d="m6 6 12 12"/>`,
    "search": `<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>`,
  };
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${C[name]}</svg>`;
}

/* ─────────────────────────────────────────────────────────────────────────
   3. State
───────────────────────────────────────────────────────────────────────── */
const RAW = JSON.parse(document.getElementById("graph-data").textContent);
const allNodes = RAW.nodes || [];
const allEdges = RAW.edges || [];
const nodeById = new Map(allNodes.map(n => [n.id, n]));

let tab = "filters";
let selectedId = null;
let selectedLabels = null;     // null == "all"
let timeRange = "all";

const TIME_OPTS = [
  { key: "1h",  label: "1h",  ms: 3600000 },
  { key: "24h", label: "24h", ms: 86400000 },
  { key: "7d",  label: "7d",  ms: 604800000 },
  { key: "30d", label: "30d", ms: 2592000000 },
  { key: "all", label: "All", ms: null },
];
function withinTimeRange(iso, key) {
  if (!iso) return key === "all";
  const o = TIME_OPTS.find(t => t.key === key);
  if (!o || o.ms === null) return true;
  return Date.now() - new Date(iso).getTime() <= o.ms;
}

const labelOptions = (() => {
  const c = new Map();
  for (const n of allNodes) for (const l of (n.labels || [])) c.set(l, (c.get(l) ?? 0) + 1);
  return [...c.entries()].map(([key, count]) => ({ key, count })).sort((a, b) => b.count - a.count);
})();

/* ─────────────────────────────────────────────────────────────────────────
   4. Cytoscape instance — same stylesheet + layout as GraphView.tsx
───────────────────────────────────────────────────────────────────────── */
if (window.cytoscape && window.cytoscapeFcose) {
  window.cytoscape.use(window.cytoscapeFcose);
}
const cy = cytoscape({
  container: document.getElementById("cy"),
  elements: [],
  style: [
    { selector: "node", style: {
        "background-color": "data(color)",
        "background-opacity": 0.95,
        "border-width": 1, "border-color": NX.void,
        label: "data(label)", color: NX.textPrimary, "font-size": 10,
        "font-family": '"JetBrains Mono","Fira Code",ui-monospace,monospace',
        "text-outline-color": NX.textOutline, "text-outline-width": 3,
        "text-valign": "bottom", "text-halign": "center", "text-margin-y": 4,
        "min-zoomed-font-size": 8, width: 18, height: 18,
    }},
    { selector: "node:active", style: { "overlay-opacity": 0 } },
    { selector: "edge", style: {
        width: 1, "line-color": NX.edge,
        "target-arrow-color": NX.edge, "target-arrow-shape": "triangle",
        "arrow-scale": 0.8, "curve-style": "bezier", opacity: 0.7,
    }},
    { selector: "edge:active", style: { "overlay-opacity": 0 } },
    { selector: "node.dimmed",  style: { opacity: 0.18, "text-opacity": 0.25 } },
    { selector: "edge.dimmed",  style: { opacity: 0.06 } },
    { selector: "node.neighbor", style: { "border-width": 2, "border-color": NX.accent, "z-index": 50 } },
    { selector: "edge.touching", style: { width: 2, "line-color": NX.accent, "target-arrow-color": NX.accent, opacity: 1, "z-index": 50 } },
    { selector: "node.selected", style: { "background-color": NX.accent, "border-width": 3, "border-color": NX.accentLight, width: 26, height: 26, "z-index": 100 } },
    { selector: "edge.selected", style: { width: 2.5, "line-color": NX.accent, "target-arrow-color": NX.accent, opacity: 1, "z-index": 100 } },
    { selector: "node.hovered",  style: { "border-width": 2, "border-color": NX.accentLight } },
    { selector: "edge.hovered",  style: { width: 2, "line-color": NX.accent, "target-arrow-color": NX.accent, opacity: 1 } },
  ],
  layout: { name: "fcose", animate: false, randomize: true, nodeRepulsion: 5500, idealEdgeLength: 110, gravity: 0.25 },
  wheelSensitivity: 0.2, minZoom: 0.2, maxZoom: 3,
});

const hoverLabelEl = document.getElementById("hover-label");
cy.on("tap", "node", (e) => onSelect(e.target.id(), "node"));
cy.on("tap", "edge", (e) => onSelect(e.target.id(), "edge"));
cy.on("mouseover", "node, edge", (e) => {
  e.target.addClass("hovered");
  const lbl = e.target.data("label") ?? "";
  hoverLabelEl.textContent = lbl;
  hoverLabelEl.style.display = lbl ? "block" : "none";
});
cy.on("mouseout", "node, edge", (e) => {
  e.target.removeClass("hovered");
  hoverLabelEl.style.display = "none";
});

/* ─────────────────────────────────────────────────────────────────────────
   5. Rendering — filters drive what's in cy.elements; rest updates panels
───────────────────────────────────────────────────────────────────────── */
function visible() {
  const ns = (selectedLabels === null)
    ? allNodes
    : allNodes.filter(n => (n.labels || []).some(l => selectedLabels.has(l)));
  const ids = new Set(ns.map(n => n.id));
  const es = allEdges.filter(e => ids.has(e.source) && ids.has(e.target) && withinTimeRange(e.valid_at, timeRange));
  return { ns, es };
}

function rebuildCytoscape() {
  const { ns, es } = visible();
  const elements = [
    ...ns.map(n => ({ data: {
      id: n.id, label: n.name || n.id.slice(0, 8),
      kind: n.kind, color: colorFor((n.labels || [])[0] ?? n.kind ?? "node"),
    }})),
    ...es.filter(e => e.source && e.target).map(e => ({ data: {
      id: e.id, source: e.source, target: e.target, label: e.fact,
    }})),
  ];
  cy.elements().remove();
  cy.add(elements);
  cy.layout({ name: "fcose", animate: false, randomize: true, nodeRepulsion: 5500, idealEdgeLength: 110, gravity: 0.25 }).run();
  // Re-apply focus mode classes against the new elements.
  applyFocus();
  // Re-render UI bits that show counts / filter chips.
  renderToolbar(ns.length, es.length);
  renderStatus(ns.length, es.length);
  document.getElementById("empty").style.display = ns.length === 0 ? "grid" : "none";
}

function applyFocus() {
  cy.batch(() => {
    cy.elements().removeClass("dimmed neighbor touching selected");
    if (!selectedId) return;
    const target = cy.$id(selectedId);
    if (target.empty()) return;
    target.addClass("selected");
    let focus = target;
    if (target.isNode()) {
      const inc = target.connectedEdges();
      const nbrs = inc.connectedNodes().difference(target);
      inc.addClass("touching"); nbrs.addClass("neighbor");
      focus = focus.union(inc).union(nbrs);
    } else {
      const ep = target.connectedNodes();
      ep.addClass("neighbor");
      focus = focus.union(ep);
    }
    cy.elements().difference(focus).addClass("dimmed");
  });
}

function onSelect(id, kind) {
  selectedId = id;
  applyFocus();
  // Auto-switch to inspector when selection lands.
  setTab("inspector");
  renderInspectorDot(true);
  renderRail();
}

/* ─────────────────────────────────────────────────────────────────────────
   6. UI builders
───────────────────────────────────────────────────────────────────────── */
function renderToolbar(vn, ve) {
  document.getElementById("toolbar-count").textContent =
    `${vn} / ${allNodes.length} nodes · ${ve} / ${allEdges.length} edges`;
}
function renderStatus(vn, ve) {
  document.getElementById("status-vn").textContent = vn;
  document.getElementById("status-tn").textContent = allNodes.length;
  document.getElementById("status-ve").textContent = ve;
  document.getElementById("status-te").textContent = allEdges.length;
  document.getElementById("status-labels").textContent =
    (selectedLabels === null) ? "All labels" : `${selectedLabels.size}/${labelOptions.length} labels`;
  document.getElementById("status-time").textContent = (timeRange === "all") ? "All time" : timeRange;
}
function renderInspectorDot(visible) {
  document.getElementById("inspector-dot").style.display = visible ? "inline-block" : "none";
}

/* ── tabs ─────────────────────────────────────────────────────────────── */
function setTab(t) {
  tab = t;
  for (const el of document.querySelectorAll(".tab-pill")) {
    el.classList.toggle("active", el.dataset.tab === t);
  }
  renderRail();
}
function toggleRail() {
  const r = document.getElementById("rail");
  r.style.display = r.style.display === "none" ? "" : "none";
}

/* ── filters ──────────────────────────────────────────────────────────── */
let labelQuery = "";
function renderFilters() {
  const allSel = (selectedLabels === null);
  const noneSel = (selectedLabels !== null && selectedLabels.size === 0);
  const showSearch = labelOptions.length > 6;
  const visibleOpts = labelQuery
    ? labelOptions.filter(o => o.key.toLowerCase().includes(labelQuery.toLowerCase()))
    : labelOptions;

  const labelRows = labelOptions.length === 0
    ? `<p style="padding:4px;font-size:12px;color:var(--nx-text-muted);">No labels in the graph yet.</p>`
    : `<ul>${visibleOpts.map(opt => {
        const active = allSel || (selectedLabels && selectedLabels.has(opt.key));
        const c = colorFor(opt.key);
        return `<li>
          <button class="row ${active ? 'active' : ''}" onclick="toggleLabel('${escId(opt.key)}')">
            <span class="swatch" style="background:${c}33"><span class="swatch-dot" style="background:${c}"></span></span>
            <code>${esc(opt.key)}</code>
            <span class="count">${opt.count}</span>
            <span class="pin"></span>
          </button>
        </li>`;
      }).join("")}</ul>`;

  const chips = TIME_OPTS.map(o =>
    `<button class="chip ${timeRange === o.key ? 'active' : ''}" onclick="setTimeRange('${o.key}')">${o.label}</button>`
  ).join("");

  return `
    <section class="section">
      <h3 class="section-title">Labels</h3>
      <div class="ms">
        ${showSearch ? `<div class="search-wrap">
          <span class="icon">${ic("search")}</span>
          <input type="text" placeholder="Search…" value="${esc(labelQuery)}" oninput="setLabelQuery(this.value)" />
        </div>` : ""}
        <div class="head">
          <button class="link ${allSel ? 'active' : ''}" onclick="selectAllLabels()">All</button>
          <span>·</span>
          <button class="link ${noneSel ? 'active' : ''}" onclick="selectNoLabels()">None</button>
          <span class="count">${labelOptions.length}</span>
        </div>
        ${labelRows}
      </div>
    </section>
    <div class="divider"></div>
    <section class="section">
      <h3 class="section-title">Time (edges)</h3>
      <p class="section-hint">Filters facts by their <code>valid_at</code> timestamp.</p>
      <div class="chips">${chips}</div>
    </section>
  `;
}

function setLabelQuery(v) {
  labelQuery = v;
  if (tab === "filters") {
    document.getElementById("rail-body").innerHTML = renderFilters();
    // Refocus the input + restore cursor.
    const input = document.querySelector("#rail-body .search-wrap input");
    if (input) { input.focus(); input.setSelectionRange(v.length, v.length); }
  }
}
function toggleLabel(k) {
  if (selectedLabels === null) {
    const s = new Set(labelOptions.map(o => o.key));
    s.delete(k);
    selectedLabels = s;
  } else {
    const s = new Set(selectedLabels);
    if (s.has(k)) s.delete(k); else s.add(k);
    selectedLabels = s;
  }
  rebuildCytoscape();
  renderRail();
}
function selectAllLabels() { selectedLabels = null; rebuildCytoscape(); renderRail(); }
function selectNoLabels()  { selectedLabels = new Set(); rebuildCytoscape(); renderRail(); }
function setTimeRange(k)   { timeRange = k; rebuildCytoscape(); renderRail(); }

/* ── inspector ────────────────────────────────────────────────────────── */
function formatShort(iso) {
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const day = 86400000;
  if (diff < day) return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (diff < 7 * day) return Math.floor(diff / day) + "d";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function renderInspector() {
  if (!selectedId) {
    return `<p style="padding:0 4px;font-size:12px;color:var(--nx-text-muted);">Click a node or fact to inspect it.</p>`;
  }
  const node = nodeById.get(selectedId);
  const edge = node ? null : allEdges.find(e => e.id === selectedId);

  if (!node && !edge) return `<p style="padding:0 4px;font-size:12px;color:var(--nx-text-muted);">Selection not found.</p>`;

  if (node) {
    const outgoing = allEdges.filter(e => e.source === node.id);
    const incoming = allEdges.filter(e => e.target === node.id);
    return `
      <div class="inspector">
        <div class="insp-head">
          <div class="title-block">
            <div class="insp-eyebrow">Entity</div>
            <div class="insp-title">${esc(node.name || "")}</div>
          </div>
          <button class="icon-btn" onclick="clearSelection()" aria-label="Clear selection" style="color:var(--nx-text-muted)">${ic("x")}</button>
        </div>
        ${node.summary ? `<div class="insp-summary">${esc(node.summary)}</div>` : ""}
        ${(node.labels && node.labels.length) ? `<div class="insp-labels">${node.labels.map(l => {
          const c = colorFor(l);
          return `<span class="insp-label" style="background:${c}22;color:${c}">${esc(l)}</span>`;
        }).join("")}</div>` : ""}
        <div class="facts-header">
          <h4>Facts</h4>
          <div class="nums">
            <span class="item">${ic("arrow-right")}<span class="tabular-nums">${outgoing.length}</span></span>
            <span class="item">${ic("arrow-left")}<span class="tabular-nums">${incoming.length}</span></span>
          </div>
        </div>
        ${(outgoing.length === 0 && incoming.length === 0) ? `<p style="padding:0 4px;font-size:12px;color:var(--nx-text-muted);">No facts touch this entity yet.</p>` : ""}
        ${outgoing.length ? renderConnGroup("Outgoing", "out", outgoing, node.id) : ""}
        ${incoming.length ? renderConnGroup("Incoming", "in",  incoming, node.id) : ""}
        <div class="insp-id" title="${esc(node.id)}">${esc(node.id)}</div>
      </div>
    `;
  }

  // edge
  const src = nodeById.get(edge.source), tgt = nodeById.get(edge.target);
  return `
    <div class="inspector">
      <div class="insp-head">
        <div class="title-block">
          <div class="insp-eyebrow">Fact</div>
          <div class="insp-title">${esc(edge.fact || "")}</div>
        </div>
        <button class="icon-btn" onclick="clearSelection()" aria-label="Clear selection" style="color:var(--nx-text-muted)">${ic("x")}</button>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <h4 style="margin:0;padding:0 4px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--nx-text-secondary);">Endpoints</h4>
        ${renderEndpoint("from", src, edge.source)}
        ${renderEndpoint("to",   tgt, edge.target)}
      </div>
      ${edge.valid_at ? `<dl style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--nx-text-muted);">
        <div style="display:flex;align-items:baseline;justify-content:space-between;gap:12px;">
          <dt style="font-weight:600;text-transform:uppercase;letter-spacing:.08em;font-size:9px;color:var(--nx-text-muted);">Valid from</dt>
          <dd style="margin:0;text-align:right;color:var(--nx-text-secondary);">${esc(new Date(edge.valid_at).toLocaleString())}</dd>
        </div>
      </dl>` : ""}
      <div class="insp-id" title="${esc(edge.id)}">${esc(edge.id)}</div>
    </div>
  `;
}
function renderConnGroup(title, dir, edges, currentId) {
  return `
    <section class="conn-group">
      <div class="conn-group-head">
        ${dir === "out" ? ic("arrow-right") : ic("arrow-left")}
        <span>${title}</span>
        <span class="nums">${edges.length}</span>
      </div>
      <ul>
        ${edges.map(e => {
          const otherId = dir === "out" ? e.target : e.source;
          const other = nodeById.get(otherId);
          if (!other || other.id === currentId) return "";
          const c = colorFor((other.labels || [])[0] ?? other.kind ?? "node");
          return `<li>
            <button class="conn-row" onclick="onSelect('${escId(other.id)}','node')">
              <div class="fact">${esc(e.fact || "")}</div>
              <div class="meta">
                <span class="arrow">${dir === "out" ? ic("arrow-right") : ic("arrow-left")}</span>
                <span class="dot" style="background:${c}33;color:${c}">●</span>
                <span class="name">${esc(other.name || "")}</span>
                ${e.valid_at ? `<span class="when" title="${esc(new Date(e.valid_at).toLocaleString())}">${esc(formatShort(e.valid_at))}</span>` : ""}
              </div>
            </button>
          </li>`;
        }).join("")}
      </ul>
    </section>
  `;
}
function renderEndpoint(role, other, otherId) {
  if (!other) {
    return `<div class="endpoint" style="cursor:default;color:var(--nx-text-muted);">${role === "from" ? "source" : "target"}: not in current view</div>`;
  }
  const c = colorFor((other.labels || [])[0] ?? other.kind ?? "node");
  return `<button class="endpoint" onclick="onSelect('${escId(other.id)}','node')">
    <span class="role">${role}</span>
    <span class="pip" style="background:${c}"></span>
    <span class="name">${esc(other.name || "")}</span>
  </button>`;
}
function clearSelection() {
  selectedId = null;
  applyFocus();
  renderInspectorDot(false);
  renderRail();
}

/* ── rail dispatch ────────────────────────────────────────────────────── */
function renderRail() {
  document.getElementById("rail-body").innerHTML =
    tab === "filters" ? renderFilters() : renderInspector();
}

/* ── escapes ──────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function escId(s) {
  // Only used inside single-quoted JS string literals in onclick attrs.
  return String(s ?? "").replace(/['\\]/g, c => "\\" + c);
}

/* ─────────────────────────────────────────────────────────────────────────
   7. Boot
───────────────────────────────────────────────────────────────────────── */
rebuildCytoscape();
renderRail();
</script>

</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://localhost:8000/api/v1/graph",
        help="Live graph endpoint to fetch from.",
    )
    parser.add_argument(
        "--tenant",
        default="default",
        help="Tenant id sent as X-Tenant-Id.",
    )
    parser.add_argument(
        "--file",
        help="Skip the API and read JSON from this file instead.",
    )
    parser.add_argument(
        "--out",
        default="exports/graph.html",
        help="Output HTML path (relative to repo root).",
    )
    args = parser.parse_args()

    if args.file:
        graph = json.loads(Path(args.file).read_text())
    else:
        resp = httpx.get(args.url, headers={"X-Tenant-Id": args.tenant}, timeout=30)
        resp.raise_for_status()
        graph = resp.json()

    n_nodes = len(graph.get("nodes", []))
    n_edges = len(graph.get("edges", []))
    print(f"loaded graph: nodes={n_nodes}, edges={n_edges}")

    # Embed as a JSON literal inside a <script type="application/json"> block.
    # Replace `</` to keep the parser from closing the script tag early.
    payload = json.dumps(graph, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.replace("__GRAPH_DATA__", payload)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
