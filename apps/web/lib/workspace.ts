import type { Project } from "@/lib/api";

// Display model for a project in the sidebar/switcher (color + mark are derived
// deterministically from the project id/name so they're stable across reloads).
export interface Ws {
  id: string;
  name: string;
  kind: string;
  color: string;
  mark: string;
}

const PALETTE = ["#FFA63D", "#8B7CF6", "#34D399", "#5B8DEF", "#22C7C0", "#F5B642", "#FF6A4D"];

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export const colorFor = (id: string): string => PALETTE[hash(id) % PALETTE.length];

export const markFor = (name: string): string =>
  (name.replace(/[^a-zA-Z0-9]/g, "").slice(0, 2) || "MG").toUpperCase();

export function toWs(p: Project, sourceCount?: number): Ws {
  const kind =
    sourceCount === undefined
      ? p.github_connected || p.slack_connected
        ? "Connected"
        : "Empty project"
      : sourceCount === 0
        ? "No sources yet"
        : `${sourceCount} source${sourceCount === 1 ? "" : "s"}`;
  return { id: p.id, name: p.name, kind, color: colorFor(p.id), mark: markFor(p.name) };
}
