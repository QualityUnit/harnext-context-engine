"use client";

import { createContext, useContext } from "react";
import type { Analytics, Project, Source } from "@/lib/api";

export type ProviderKind = "github" | "slack" | "discord" | "liveagent" | "youtube";

// Shared dashboard state + mutations, fetched once in the project layout and
// consumed by each view's route page so navigating between views never refetches
// the project/sources/analytics that the whole shell depends on.
export interface DashboardValue {
  id: string;
  project: Project;
  sources: Source[];
  analytics?: Analytics;
  refresh: () => void;
  onSync: (sourceId: string) => void;
  onRemove: (sourceId: string) => void;
  onRename: (name: string) => void;
  onDisconnect: (kind: ProviderKind) => void;
  onDelete: () => void;
}

const DashboardContext = createContext<DashboardValue | null>(null);

export const DashboardProvider = DashboardContext.Provider;

export function useDashboard(): DashboardValue {
  const value = useContext(DashboardContext);
  if (!value) throw new Error("useDashboard must be used within the project dashboard layout");
  return value;
}
