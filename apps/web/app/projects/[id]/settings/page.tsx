"use client";

import { SettingsView } from "@/components/dashboard/SettingsView";
import { useDashboard } from "../dashboard-context";

export default function SettingsPage() {
  const { project, sources, onRename, onRemove, onDisconnect, onDelete } = useDashboard();
  return (
    <SettingsView
      project={project}
      sources={sources}
      onRename={onRename}
      onRemoveSource={onRemove}
      onDisconnect={onDisconnect}
      onDelete={onDelete}
    />
  );
}
