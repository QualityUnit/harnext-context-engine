"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher, type Analytics, type Project, type Source } from "@/lib/api";
import { clearSession, useUser } from "@/lib/auth";
import { toWs } from "@/lib/workspace";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { DashboardProvider, type ProviderKind } from "./dashboard-context";

const OAUTH_ERRORS: Record<string, string> = {
  oauth_not_configured: "That provider isn't configured on this instance yet.",
  HTTPStatusError: "The provider rejected the request. Check the app's redirect URL and try again.",
  OAuthError: "Authorization failed. Please try again.",
};

// The project dashboard shell: sidebar + the shared data every view reads. Each
// view lives at its own route (see the sibling page.tsx files) and renders into
// {children}; this layout persists across those navigations so the sidebar and
// the project/sources/analytics polling are never torn down between views.
export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const user = useUser();
  const router = useRouter();
  const search = useSearchParams();
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  const projects = useSWR<Project[]>(user ? "/projects" : null, fetcher);
  const project = useSWR<Project>(user ? `/projects/${id}` : null, fetcher, { refreshInterval: 8000 });
  const sources = useSWR<Source[]>(user ? `/sources?project_id=${id}` : null, fetcher, {
    refreshInterval: 5000,
  });
  const analytics = useSWR<Analytics>(user ? `/projects/${id}/analytics` : null, fetcher, {
    refreshInterval: 8000,
  });

  // Surface the OAuth callback result (?connected / ?error), then clean the URL.
  useEffect(() => {
    const connected = search.get("connected");
    const err = search.get("error");
    if (!connected && !err) return;
    if (connected) {
      setBanner({
        kind: "ok",
        msg: `${connected[0].toUpperCase() + connected.slice(1)} connected — add a ${connected === "github" ? "repository" : "channel"} below.`,
      });
      project.mutate();
      sources.mutate();
    } else if (err) {
      setBanner({ kind: "err", msg: OAUTH_ERRORS[err] ?? `Connect failed: ${err}` });
    }
    router.replace(`/projects/${id}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, id]);

  if (!user) return null;

  const refresh = () => {
    project.mutate();
    projects.mutate();
    sources.mutate();
    analytics.mutate();
  };

  // ---- handlers ----
  const onSwitch = (pid: string) => {
    if (pid !== id) router.push(`/projects/${pid}`);
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

  const onDisconnect = async (kind: ProviderKind) => {
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
  const workspaces = (projects.data ?? [project.data]).map((p) => (p.id === id ? current : toWs(p)));

  return (
    <div className="app">
      <Sidebar
        id={id}
        workspaces={workspaces}
        current={current}
        user={user}
        onSwitch={onSwitch}
        onCreate={onCreate}
        onLogout={onLogout}
      />
      <main className="main">
        <div className="main-inner">
          {banner && (
            <div className={"banner " + banner.kind}>
              <span>{banner.msg}</span>
              <button onClick={() => setBanner(null)} aria-label="Dismiss">
                ✕
              </button>
            </div>
          )}
          <DashboardProvider
            value={{
              id,
              project: project.data,
              sources: srcList,
              analytics: analytics.data,
              refresh,
              onSync,
              onRemove,
              onRename,
              onDisconnect,
              onDelete,
            }}
          >
            {children}
          </DashboardProvider>
        </div>
      </main>
    </div>
  );
}
