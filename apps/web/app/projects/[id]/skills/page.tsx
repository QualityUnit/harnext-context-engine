"use client";

import { SkillsView } from "@/components/dashboard/SkillsView";
import { useDashboard } from "../dashboard-context";

export default function SkillsPage() {
  const { project } = useDashboard();
  return <SkillsView project={project} />;
}
