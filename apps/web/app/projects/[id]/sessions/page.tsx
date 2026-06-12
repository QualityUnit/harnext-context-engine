"use client";

import useSWR from "swr";
import { fetcher, type AgentSession } from "@/lib/api";
import { useUser } from "@/lib/auth";
import { SessionsView } from "@/components/dashboard/SessionsView";
import { useDashboard } from "../dashboard-context";

// The "Sessions" view: conversations a harness pushes to this project. The list
// is polled while mounted so live sessions stream in; selecting one loads its
// full transcript.
export default function SessionsPage() {
  const user = useUser();
  const { id, project } = useDashboard();
  const sessions = useSWR<AgentSession[]>(
    user ? `/projects/${id}/agent-sessions?limit=100` : null,
    fetcher,
    { refreshInterval: 5000, keepPreviousData: true },
  );
  return <SessionsView project={project} sessions={sessions.data ?? []} />;
}
