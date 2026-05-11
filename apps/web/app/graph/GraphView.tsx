"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
// eslint-disable-next-line @typescript-eslint/no-require-imports
const fcose = require("cytoscape-fcose");
import type { GraphResponse } from "@/lib/types";

if (typeof cytoscape !== "undefined" && !(cytoscape as unknown as { __fcoseRegistered?: boolean }).__fcoseRegistered) {
  cytoscape.use(fcose);
  (cytoscape as unknown as { __fcoseRegistered: boolean }).__fcoseRegistered = true;
}

export default function GraphView({
  data,
  onSelect,
}: {
  data: GraphResponse;
  onSelect?: (id: string, kind: "node" | "edge") => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [hoverLabel, setHoverLabel] = useState<string | null>(null);

  const elements = useMemo<ElementDefinition[]>(() => {
    const nodes = data.nodes.map((n) => ({
      data: { id: n.id, label: n.name || n.id.slice(0, 8), kind: n.kind, summary: n.summary },
    }));
    const edges = data.edges
      .filter((e) => e.source && e.target)
      .map((e) => ({
        data: { id: e.id, source: e.source, target: e.target, label: e.fact },
      }));
    return [...nodes, ...edges];
  }, [data]);

  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "#6366f1",
            label: "data(label)",
            color: "#111",
            "font-size": 11,
            "text-outline-color": "#fff",
            "text-outline-width": 2,
            "text-valign": "center",
            "text-halign": "center",
            width: 28,
            height: 28,
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#9ca3af",
            "target-arrow-color": "#9ca3af",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            opacity: 0.7,
          },
        },
        {
          selector: ":selected",
          style: { "background-color": "#f59e0b", "line-color": "#f59e0b", "target-arrow-color": "#f59e0b" },
        },
      ],
      layout: {
        name: "fcose",
        animate: false,
        randomize: true,
        nodeRepulsion: 4500,
        idealEdgeLength: 90,
      } as unknown as cytoscape.LayoutOptions,
      wheelSensitivity: 0.2,
    });

    cy.on("tap", "node", (evt) => onSelectRef.current?.(evt.target.id(), "node"));
    cy.on("tap", "edge", (evt) => onSelectRef.current?.(evt.target.id(), "edge"));
    cy.on("mouseover", "node, edge", (evt) => setHoverLabel(evt.target.data("label") ?? null));
    cy.on("mouseout", "node, edge", () => setHoverLabel(null));

    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [elements]);

  return (
    <div className="relative w-full h-full">
      {/* Cytoscape sets position:relative on the container, so we can't use
          absolute-inset-0 (collapses to height:0). Give it explicit w/h. */}
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
      {hoverLabel && (
        <div className="absolute bottom-2 left-2 max-w-md text-xs bg-black/80 text-white rounded px-2 py-1 truncate z-10">
          {hoverLabel}
        </div>
      )}
    </div>
  );
}
