import type { Source } from "@/lib/api";

export function formatBytes(n: number): [string, string] {
  if (n >= 1e9) return [(n / 1e9).toFixed(2), "GB"];
  if (n >= 1e6) return [(n / 1e6).toFixed(2), "MB"];
  if (n >= 1e3) return [(n / 1e3).toFixed(1), "KB"];
  return [String(n), "B"];
}

export function rel(iso: string | null): string {
  if (!iso) return "never";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

export const cfg = (s: Source, k: string): string => {
  const v = (s.config as Record<string, unknown>)[k];
  return typeof v === "string" ? v : "";
};

export function sourceName(s: Source): string {
  if (s.kind === "github") return cfg(s, "repo") || "repository";
  if (s.kind === "youtube")
    return cfg(s, "channel_name") || cfg(s, "channel_id") || cfg(s, "channel_url") || "channel";
  return cfg(s, "channel_name") ? `#${cfg(s, "channel_name")}` : cfg(s, "channel_id") || "channel";
}

export type UiStatus = "live" | "backfill" | "error" | "paused";

export function uiStatus(s: Source): UiStatus {
  if (s.status === "error") return "error";
  if (s.status === "paused") return "paused";
  return s.last_sync_at ? "live" : "backfill";
}

export const STATUS: Record<UiStatus, { label: string; cls: string }> = {
  live: { label: "Live", cls: "ok" },
  backfill: { label: "Backfilling", cls: "busy" },
  error: { label: "Error", cls: "err" },
  paused: { label: "Paused", cls: "mut" },
};
