"use client";

import useSWR from "swr";
import { fetcher, type FsList } from "@/lib/api";
import { useUser } from "@/lib/auth";
import { FilesView } from "@/components/dashboard/FilesView";
import { useDashboard } from "../dashboard-context";

// The "Files" view: browse + edit the agent's context filesystem. The list is a
// one-shot fetch (not polled); navigating away unmounts the page and SWR's cache
// serves it instantly on return, so the explorer is never empty on revisit.
export default function FilesPage() {
  const user = useUser();
  const { id, project } = useDashboard();
  const fs = useSWR<FsList>(user ? `/projects/${id}/fs` : null, fetcher, {
    keepPreviousData: true,
  });
  return (
    <FilesView
      project={project}
      files={fs.data?.files ?? []}
      snapshotId={fs.data?.snapshot_id ?? null}
      loading={fs.isLoading}
      onReload={() => fs.mutate()}
    />
  );
}
