"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
// eslint-disable-next-line @typescript-eslint/no-require-imports
const fcose = require("cytoscape-fcose");
import type { GraphResponse } from "@/lib/types";
import { colorFor } from "@/lib/colors";

if (
  typeof cytoscape !== "undefined" &&
  !(cytoscape as unknown as { __fcoseRegistered?: boolean }).__fcoseRegistered
) {
  cytoscape.use(fcose);
  (cytoscape as unknown as { __fcoseRegistered: boolean }).__fcoseRegistered =
    true;
}

const NX = {
  bg: "#06060a",
  textOutline: "#06060a",
  textPrimary: "#e4e4ed",
  edge: "#2a2a3a",
  accent: "#7c3aed",
  accentLight: "#a78bfa",
};

function nodeColor(kind: string, labels: string[]): string {
  return colorFor(labels[0] ?? kind ?? "node");
}

export default function GraphView({
  data,
  selectedId,
  onSelect,
}: {
  data: GraphResponse;
  selectedId?: string | null;
  onSelect?: (id: string, kind: "node" | "edge") => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [hoverLabel, setHoverLabel] = useState<string | null>(null);

  const elements = useMemo<ElementDefinition[]>(() => {
    const nodes = data.nodes.map((n) => ({
      data: {
        id: n.id,
        label: n.name || n.id.slice(0, 8),
        kind: n.kind,
        summary: n.summary,
        color: nodeColor(n.kind, n.labels),
      },
    }));
    const edges = data.edges
      .filter((e) => e.source && e.target)
      .map((e) => ({
        data: { id: e.id, source: e.source, target: e.target, label: e.fact },
      }));
    return [...nodes, ...edges];
  }, [data]);

  // Build (and tear down) the Cytoscape instance whenever the underlying
  // elements list changes. Selection highlight runs as a separate effect so
  // changing the selection doesn't trigger a relayout.
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            "background-opacity": 0.95,
            "border-width": 1,
            "border-color": NX.bg,
            label: "data(label)",
            color: NX.textPrimary,
            "font-size": 10,
            "font-family":
              '"JetBrains Mono", "Fira Code", ui-monospace, monospace',
            "text-outline-color": NX.textOutline,
            "text-outline-width": 3,
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 4,
            "min-zoomed-font-size": 8,
            width: 18,
            height: 18,
          },
        },
        { selector: "node:active", style: { "overlay-opacity": 0 } },
        {
          selector: "edge",
          style: {
            width: 1,
            "line-color": NX.edge,
            "target-arrow-color": NX.edge,
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.8,
            "curve-style": "bezier",
            opacity: 0.7,
          },
        },
        { selector: "edge:active", style: { "overlay-opacity": 0 } },

        // ── focus mode ────────────────────────────────────────────────
        // Anything outside the 1-hop neighborhood of the selection gets
        // dimmed; the selection itself, its neighbors, and the edges that
        // touch it stay vivid.
        {
          selector: "node.dimmed",
          style: { opacity: 0.18, "text-opacity": 0.25 },
        },
        {
          selector: "edge.dimmed",
          style: { opacity: 0.06 },
        },
        {
          selector: "node.neighbor",
          style: {
            "border-width": 2,
            "border-color": NX.accent,
            "z-index": 50,
          },
        },
        {
          selector: "edge.touching",
          style: {
            width: 2,
            "line-color": NX.accent,
            "target-arrow-color": NX.accent,
            opacity: 1,
            "z-index": 50,
          },
        },
        {
          selector: "node.selected",
          style: {
            "background-color": NX.accent,
            "border-width": 3,
            "border-color": NX.accentLight,
            width: 26,
            height: 26,
            "z-index": 100,
          },
        },
        {
          selector: "edge.selected",
          style: {
            width: 2.5,
            "line-color": NX.accent,
            "target-arrow-color": NX.accent,
            opacity: 1,
            "z-index": 100,
          },
        },

        // ── hover ─────────────────────────────────────────────────────
        {
          selector: "node.hovered",
          style: { "border-width": 2, "border-color": NX.accentLight },
        },
        {
          selector: "edge.hovered",
          style: {
            width: 2,
            "line-color": NX.accent,
            "target-arrow-color": NX.accent,
            opacity: 1,
          },
        },
      ],
      layout: {
        name: "fcose",
        animate: false,
        randomize: true,
        nodeRepulsion: 5500,
        idealEdgeLength: 110,
        gravity: 0.25,
      } as unknown as cytoscape.LayoutOptions,
      wheelSensitivity: 0.2,
      minZoom: 0.2,
      maxZoom: 3,
    });

    cy.on("tap", "node", (evt) =>
      onSelectRef.current?.(evt.target.id(), "node"),
    );
    cy.on("tap", "edge", (evt) =>
      onSelectRef.current?.(evt.target.id(), "edge"),
    );
    cy.on("mouseover", "node", (evt) => {
      evt.target.addClass("hovered");
      setHoverLabel(evt.target.data("label") ?? null);
    });
    cy.on("mouseover", "edge", (evt) => {
      evt.target.addClass("hovered");
      setHoverLabel(evt.target.data("label") ?? null);
    });
    cy.on("mouseout", "node, edge", (evt) => {
      evt.target.removeClass("hovered");
      setHoverLabel(null);
    });

    cyRef.current = cy;
    // Dev-only escape hatch for inspection / testing in the console.
    if (typeof window !== "undefined") {
      (window as unknown as { __cy?: Core }).__cy = cy;
    }
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [elements]);

  // Apply focus-mode classes when selection changes.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.batch(() => {
      cy.elements().removeClass("dimmed neighbor touching selected");

      if (!selectedId) return;
      const target = cy.$id(selectedId);
      if (target.empty()) return;

      let focus = target;
      target.addClass("selected");

      // `target` is a Singular collection; isNode() narrows it for TS but
      // also collapses the else branch to `never`, so use the boolean result
      // directly and re-grab the collection inside each branch.
      const targetIsNode = target.isNode();
      if (targetIsNode) {
        const sel = cy.$id(selectedId);
        const incidentEdges = sel.connectedEdges();
        const neighborNodes = incidentEdges.connectedNodes().difference(sel);
        incidentEdges.addClass("touching");
        neighborNodes.addClass("neighbor");
        focus = focus.union(incidentEdges).union(neighborNodes);
      } else {
        const sel = cy.$id(selectedId);
        const endpoints = sel.connectedNodes();
        endpoints.addClass("neighbor");
        focus = focus.union(endpoints);
      }

      cy.elements().difference(focus).addClass("dimmed");
    });
  }, [selectedId, elements]);

  return (
    <div className="relative h-full w-full">
      <div
        ref={containerRef}
        style={{
          width: "100%",
          height: "100%",
          backgroundColor: NX.bg,
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.04) 1px, transparent 0)",
          backgroundSize: "24px 24px",
        }}
      />
      {hoverLabel && (
        <div
          className="pointer-events-none absolute bottom-3 left-3 z-10 max-w-md truncate rounded border px-2 py-1 font-mono text-[11px] backdrop-blur"
          style={{
            backgroundColor: "rgba(16, 16, 24, 0.92)",
            borderColor: "var(--nx-border-subtle)",
            color: "var(--nx-text-primary)",
          }}
        >
          {hoverLabel}
        </div>
      )}
    </div>
  );
}
