"use client";

import { ConnectView } from "@/components/dashboard/ConnectView";
import { useDashboard } from "../dashboard-context";

export default function ConnectPage() {
  const { project, sources } = useDashboard();
  return <ConnectView project={project} sources={sources} />;
}
