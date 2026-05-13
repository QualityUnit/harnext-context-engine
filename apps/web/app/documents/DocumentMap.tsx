"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { DocumentPoint } from "@/lib/types";

const PADDING = 36;
const DOT_RADIUS = 5;
const HOVER_RADIUS = 9;

// Stable color hash for arbitrary source strings (events, file uploads, …)
const PALETTE = [
  "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#06b6d4",
  "#a855f7", "#ec4899", "#14b8a6", "#f97316", "#84cc16",
];
function colorFor(source: string): string {
  let h = 0;
  for (let i = 0; i < source.length; i++) h = (h * 31 + source.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

type Bounds = { minX: number; maxX: number; minY: number; maxY: number };

function computeBounds(points: DocumentPoint[]): Bounds {
  if (points.length === 0) return { minX: -1, maxX: 1, minY: -1, maxY: 1 };
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  // Avoid zero-width when there's a single cluster
  if (maxX - minX < 1e-6) { minX -= 0.5; maxX += 0.5; }
  if (maxY - minY < 1e-6) { minY -= 0.5; maxY += 0.5; }
  return { minX, maxX, minY, maxY };
}

export default function DocumentMap({
  points,
  onSelect,
  selectedId,
}: {
  points: DocumentPoint[];
  onSelect: (p: DocumentPoint | null) => void;
  selectedId: string | null;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState<{ p: DocumentPoint; px: number; py: number } | null>(null);

  const bounds = useMemo(() => computeBounds(points), [points]);

  // Track container size
  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const r = e.contentRect;
        setSize({ w: r.width, h: r.height });
      }
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  // Project a data point to pixel coords (memoized for hit-tests + draw)
  const project = useMemo(() => {
    const { minX, maxX, minY, maxY } = bounds;
    const drawW = Math.max(1, size.w - PADDING * 2);
    const drawH = Math.max(1, size.h - PADDING * 2);
    return (x: number, y: number) => {
      const nx = (x - minX) / (maxX - minX);
      const ny = (y - minY) / (maxY - minY);
      // Flip Y so positive PCA-y points up
      return { px: PADDING + nx * drawW, py: PADDING + (1 - ny) * drawH };
    };
  }, [bounds, size.w, size.h]);

  // Draw
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || size.w === 0 || size.h === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(size.w * dpr);
    canvas.height = Math.floor(size.h * dpr);
    canvas.style.width = `${size.w}px`;
    canvas.style.height = `${size.h}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);

    // axes / frame
    ctx.strokeStyle = "rgba(0,0,0,0.08)";
    ctx.lineWidth = 1;
    ctx.strokeRect(PADDING - 0.5, PADDING - 0.5, size.w - PADDING * 2 + 1, size.h - PADDING * 2 + 1);

    // dots
    for (const p of points) {
      const { px, py } = project(p.x, p.y);
      const isSelected = p.event_id === selectedId;
      ctx.beginPath();
      ctx.arc(px, py, isSelected ? HOVER_RADIUS : DOT_RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = colorFor(p.source);
      ctx.globalAlpha = isSelected ? 1 : 0.85;
      ctx.fill();
      if (isSelected) {
        ctx.strokeStyle = "#111";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
  }, [points, project, selectedId, size.w, size.h]);

  function hitTest(clientX: number, clientY: number): DocumentPoint | null {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const mx = clientX - rect.left;
    const my = clientY - rect.top;
    let best: { p: DocumentPoint; d: number } | null = null;
    for (const p of points) {
      const { px, py } = project(p.x, p.y);
      const dx = px - mx, dy = py - my;
      const d2 = dx * dx + dy * dy;
      if (d2 < HOVER_RADIUS * HOVER_RADIUS && (!best || d2 < best.d)) {
        best = { p, d: d2 };
      }
    }
    return best?.p ?? null;
  }

  return (
    <div ref={wrapRef} className="relative w-full h-full">
      <canvas
        ref={canvasRef}
        onMouseMove={(e) => {
          const p = hitTest(e.clientX, e.clientY);
          if (!p) {
            setHover(null);
            return;
          }
          const { px, py } = project(p.x, p.y);
          setHover({ p, px, py });
        }}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          const p = hitTest(e.clientX, e.clientY);
          onSelect(p);
        }}
        className="block cursor-crosshair"
      />
      {hover && (
        <div
          className="absolute pointer-events-none rounded-md border border-black/10 dark:border-white/15 bg-white/95 dark:bg-black/85 px-2 py-1 text-xs shadow-sm max-w-xs"
          style={{
            left: Math.min(hover.px + 10, size.w - 280),
            top: Math.max(0, hover.py - 8),
          }}
        >
          <div className="font-mono text-[11px] opacity-60">{hover.p.source}</div>
          <div className="font-medium truncate">{hover.p.subject}</div>
          {hover.p.text_preview && (
            <div className="opacity-70 mt-0.5 line-clamp-2">{hover.p.text_preview}</div>
          )}
        </div>
      )}
    </div>
  );
}
