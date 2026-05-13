"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { DocumentPoint } from "@/lib/types";
import { colorFor } from "@/lib/colors";

const PADDING = { top: 56, right: 80, bottom: 56, left: 80 };
const DOT_RADIUS = 5;
const HOVER_RADIUS = 9;

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
  if (maxX - minX < 1e-6) { minX -= 0.5; maxX += 0.5; }
  if (maxY - minY < 1e-6) { minY -= 0.5; maxY += 0.5; }
  // Symmetric pad so axes don't crowd outermost points (~6%).
  const padX = (maxX - minX) * 0.06;
  const padY = (maxY - minY) * 0.06;
  return { minX: minX - padX, maxX: maxX + padX, minY: minY - padY, maxY: maxY + padY };
}

// Pleasant tick step (1·10^k, 2·10^k, 5·10^k).
function niceStep(range: number, targetTicks: number) {
  const rough = range / Math.max(1, targetTicks);
  const pow10 = Math.pow(10, Math.floor(Math.log10(rough)));
  const norm = rough / pow10;
  let step;
  if (norm < 1.5) step = 1;
  else if (norm < 3) step = 2;
  else if (norm < 7) step = 5;
  else step = 10;
  return step * pow10;
}
function ticksFor(min: number, max: number, target = 6): number[] {
  const step = niceStep(max - min, target);
  const start = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + step * 0.5; v += step) out.push(v);
  return out;
}
function formatTick(v: number) {
  if (v === 0) return "0";
  const abs = Math.abs(v);
  if (abs >= 100 || abs < 0.01) return v.toExponential(0);
  return v.toFixed(abs < 1 ? 2 : abs < 10 ? 1 : 0);
}

export default function DocumentMap({
  points,
  onSelect,
  selectedId,
  varianceExplained,
}: {
  points: DocumentPoint[];
  onSelect: (p: DocumentPoint | null) => void;
  selectedId: string | null;
  varianceExplained?: [number, number];
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState<{ p: DocumentPoint; px: number; py: number } | null>(null);
  const [isDark, setIsDark] = useState(false);

  const bounds = useMemo(() => computeBounds(points), [points]);

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

  // Track dark mode via the .dark class on <html> (next-themes).
  useEffect(() => {
    const el = document.documentElement;
    const update = () => setIsDark(el.classList.contains("dark"));
    update();
    const obs = new MutationObserver(update);
    obs.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  const project = useMemo(() => {
    const { minX, maxX, minY, maxY } = bounds;
    const drawW = Math.max(1, size.w - PADDING.left - PADDING.right);
    const drawH = Math.max(1, size.h - PADDING.top - PADDING.bottom);
    return (x: number, y: number) => {
      const nx = (x - minX) / (maxX - minX);
      const ny = (y - minY) / (maxY - minY);
      return { px: PADDING.left + nx * drawW, py: PADDING.top + (1 - ny) * drawH };
    };
  }, [bounds, size.w, size.h]);

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

    const innerLeft = PADDING.left;
    const innerRight = size.w - PADDING.right;
    const innerTop = PADDING.top;
    const innerBottom = size.h - PADDING.bottom;

    const gridColor = isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)";
    const axisColor = isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.3)";
    const tickTextColor = isDark ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.55)";
    const labelColor = isDark ? "rgba(255,255,255,0.7)" : "rgba(0,0,0,0.7)";

    ctx.font = "10px ui-sans-serif, system-ui, sans-serif";

    // grid + ticks
    const xt = ticksFor(bounds.minX, bounds.maxX);
    const yt = ticksFor(bounds.minY, bounds.maxY);

    ctx.lineWidth = 1;
    ctx.strokeStyle = gridColor;
    ctx.beginPath();
    for (const v of xt) {
      const { px } = project(v, bounds.minY);
      ctx.moveTo(px + 0.5, innerTop);
      ctx.lineTo(px + 0.5, innerBottom);
    }
    for (const v of yt) {
      const { py } = project(bounds.minX, v);
      ctx.moveTo(innerLeft, py + 0.5);
      ctx.lineTo(innerRight, py + 0.5);
    }
    ctx.stroke();

    // axes (left + bottom)
    ctx.strokeStyle = axisColor;
    ctx.beginPath();
    ctx.moveTo(innerLeft + 0.5, innerTop);
    ctx.lineTo(innerLeft + 0.5, innerBottom + 0.5);
    ctx.lineTo(innerRight, innerBottom + 0.5);
    ctx.stroke();

    // tick labels
    ctx.fillStyle = tickTextColor;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const v of xt) {
      const { px } = project(v, bounds.minY);
      ctx.fillText(formatTick(v), px, innerBottom + 6);
    }
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (const v of yt) {
      const { py } = project(bounds.minX, v);
      ctx.fillText(formatTick(v), innerLeft - 8, py);
    }

    // axis labels
    const v1 = varianceExplained?.[0];
    const v2 = varianceExplained?.[1];
    const pc1Label = v1 !== undefined ? `PC1 — ${Math.round(v1 * 100)}% variance` : "PC1";
    const pc2Label = v2 !== undefined ? `PC2 — ${Math.round(v2 * 100)}% variance` : "PC2";

    ctx.fillStyle = labelColor;
    ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(pc1Label, (innerLeft + innerRight) / 2, size.h - 14);

    ctx.save();
    ctx.translate(20, (innerTop + innerBottom) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(pc2Label, 0, 0);
    ctx.restore();

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
        ctx.strokeStyle = isDark ? "#fff" : "#111";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
  }, [points, project, selectedId, size.w, size.h, bounds, varianceExplained, isDark]);

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
          className="absolute pointer-events-none rounded-md border bg-popover/95 backdrop-blur px-2 py-1 text-xs shadow-md max-w-xs"
          style={{
            left: Math.min(hover.px + 10, size.w - 280),
            top: Math.max(0, hover.py - 8),
          }}
        >
          <div className="font-mono text-[11px] text-muted-foreground">{hover.p.source}</div>
          <div className="font-medium truncate">{hover.p.subject}</div>
          {hover.p.text_preview && (
            <div className="text-muted-foreground mt-0.5 line-clamp-2">{hover.p.text_preview}</div>
          )}
        </div>
      )}
    </div>
  );
}
