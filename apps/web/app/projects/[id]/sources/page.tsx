"use client";

import { SourcesView } from "@/components/dashboard/SourcesView";
import { useDashboard } from "../dashboard-context";

export default function SourcesPage() {
  const { project, sources, analytics, onSync, onRemove, refresh } = useDashboard();
  return (
    <SourcesView
      project={project}
      sources={sources}
      analytics={analytics}
      onSync={onSync}
      onRemove={onRemove}
      onChanged={refresh}
    />
  );
}
