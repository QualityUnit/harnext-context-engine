"use client";

import { useParams } from "next/navigation";
import { Dashboard } from "@/components/dashboard/Dashboard";

export default function ProjectDashboardPage() {
  const { id } = useParams<{ id: string }>();
  return <Dashboard id={id} />;
}
