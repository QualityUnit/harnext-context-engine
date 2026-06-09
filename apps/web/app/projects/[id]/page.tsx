"use client";

import useSWR from "swr";
import { fetcher, type McpRequest, type McpStats } from "@/lib/api";
import { useUser } from "@/lib/auth";
import { MCPView } from "@/components/dashboard/MCPView";
import { useDashboard } from "./dashboard-context";

// The default project view ("Dashboard" in the sidebar). MCP activity is polled
// only here, so it naturally stops when the user navigates to another view.
export default function DashboardPage() {
  const user = useUser();
  const { id, project } = useDashboard();
  const stats = useSWR<McpStats>(user ? `/projects/${id}/mcp-requests/stats` : null, fetcher, {
    refreshInterval: 5000,
  });
  const requests = useSWR<McpRequest[]>(user ? `/projects/${id}/mcp-requests?limit=100` : null, fetcher, {
    refreshInterval: 5000,
  });
  return <MCPView project={project} requests={requests.data ?? []} stats={stats.data} />;
}
