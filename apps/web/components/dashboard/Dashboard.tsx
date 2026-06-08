"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, fetcher, type Analytics, type Project, type Source } from "@/lib/api";
import { clearSession, useUser } from "@/lib/auth";
import { toWs } from "@/lib/workspace";
import { Sidebar, type View } from "@/components/dashboard/Sidebar";
import { SourcesView } from "@/components/dashboard/SourcesView";
import { ConnectView } from "@/components/dashboard/ConnectView";
import { SettingsView } from "@/components/dashboard/SettingsView";

export function Dashboard({ id }: { id: string }) {
  const user = useUser();
  const router = useRouter();
  const [view, setView] = useState<View>("sources");

  const projects = useSWR<Project[]>(user ? "/projects" : null, fetcher);
  const project = useSWR<Project>(user ? `/projects/${id}` : null, fetcher, { refreshInterval: 8000 });
  const sources = useSWR<Source[]>(user ? `/sources?project_id=${id}` : null, fetcher, {
    refreshInterval: 5000,
  });
  const analytics = useSWR<Analytics>(user ? `/projects/${id}/analytics` : null, fetcher, {
    refreshInterval: 8000,
  });

  if (!user) return null;

  const refresh = () => {
    project.mutate();
    projects.mutate();
    sources.mutate();
    analytics.mutate();
  };

  // ---- handlers ----
  const onSwitch = (pid: string) => {
    if (pid !== id) {
      setView("sources");
      router.push(`/projects/${pid}`);
    }
  };

  const onCreate = async () => {
    const n = (projects.data?.length ?? 0) + 1;
    const p = await api.createProject(`project-${n}`);
    projects.mutate();
    router.push(`/projects/${p.id}`);
  };

  const onLogout = () => {
    clearSession();
    router.replace("/login");
  };

  const onSync = async (sourceId: string) => {
    try {
      await api.syncSource(sourceId);
    } catch {
      /* surfaced as the source's Error status */
    }
    sources.mutate();
    analytics.mutate();
  };

  const onRemove = async (sourceId: string) => {
    await api.deleteSource(sourceId);
    refresh();
  };

  const onRename = async (name: string) => {
    await api.renameProject(id, name);
    project.mutate();
    projects.mutate();
  };

  const onDisconnect = async (kind: "github" | "slack") => {
    await api.disconnectProvider(id, kind);
    refresh();
  };

  const onDelete = async () => {
    try {
      await api.deleteProject(id);
      router.push("/projects");
    } catch (e) {
      alert(`Could not delete project: ${e}`);
    }
  };

  // ---- loading ----
  if (!project.data) {
    return (
      <div className="app">
        <div className="sidebar" />
        <main className="main">
          <div className="main-inner">
            <p style={{ color: "var(--tx-2)", fontSize: 13, padding: 24 }}>Loading…</p>
          </div>
        </main>
      </div>
    );
  }

  const srcList = sources.data ?? [];
  const current = toWs(project.data, srcList.length);
  const workspaces = (projects.data ?? [project.data]).map((p) =>
    p.id === id ? current : toWs(p),
  );

  return (
    <div className="app">
      <Sidebar
        workspaces={workspaces}
        current={current}
        view={view}
        user={user}
        onView={setView}
        onSwitch={onSwitch}
        onCreate={onCreate}
        onLogout={onLogout}
      />
      <main className="main">
        <div className="main-inner">
          {view === "sources" ? (
            <SourcesView
              project={project.data}
              sources={srcList}
              analytics={analytics.data}
              onSync={onSync}
              onRemove={onRemove}
              onChanged={refresh}
            />
          ) : view === "connect" ? (
            <ConnectView project={project.data} sources={srcList} />
          ) : (
            <SettingsView
              project={project.data}
              sources={srcList}
              onRename={onRename}
              onRemoveSource={onRemove}
              onDisconnect={onDisconnect}
              onDelete={onDelete}
            />
          )}
        </div>
      </main>
    </div>
  );
}
