"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import {
  api,
  fetcher,
  type Analytics,
  type FsList,
  type McpRequest,
  type McpStats,
  type Project,
  type Source,
} from "@/lib/api";
import { clearSession, useUser } from "@/lib/auth";
import { toWs } from "@/lib/workspace";
import { Sidebar, type View } from "@/components/dashboard/Sidebar";
import { SourcesView } from "@/components/dashboard/SourcesView";
import { ConnectView } from "@/components/dashboard/ConnectView";
import { MCPView } from "@/components/dashboard/MCPView";
import { FilesView } from "@/components/dashboard/FilesView";
import { SettingsView } from "@/components/dashboard/SettingsView";

const OAUTH_ERRORS: Record<string, string> = {
  oauth_not_configured: "That provider isn't configured on this instance yet.",
  HTTPStatusError: "The provider rejected the request. Check the app's redirect URL and try again.",
  OAuthError: "Authorization failed. Please try again.",
};

export function Dashboard({ id }: { id: string }) {
  const user = useUser();
  const router = useRouter();
  const search = useSearchParams();
  const [view, setView] = useState<View>("mcp");
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  // Remember the project whose Files view has been opened, so its file list
  // stays subscribed across view switches (a conditional `null` key would drop
  // the data, leaving the explorer empty until a manual refresh on return).
  const [filesSeenFor, setFilesSeenFor] = useState<string | null>(null);
  useEffect(() => {
    if (view === "files") setFilesSeenFor(id);
  }, [view, id]);

  const projects = useSWR<Project[]>(user ? "/projects" : null, fetcher);
  const project = useSWR<Project>(user ? `/projects/${id}` : null, fetcher, { refreshInterval: 8000 });
  const sources = useSWR<Source[]>(user ? `/sources?project_id=${id}` : null, fetcher, {
    refreshInterval: 5000,
  });
  const analytics = useSWR<Analytics>(user ? `/projects/${id}/analytics` : null, fetcher, {
    refreshInterval: 8000,
  });
  // MCP activity is only polled while its view is open.
  const mcpStats = useSWR<McpStats>(
    user && view === "mcp" ? `/projects/${id}/mcp-requests/stats` : null,
    fetcher,
    { refreshInterval: 5000 },
  );
  const mcpRequests = useSWR<McpRequest[]>(
    user && view === "mcp" ? `/projects/${id}/mcp-requests?limit=100` : null,
    fetcher,
    { refreshInterval: 5000 },
  );
  // The agent's context filesystem. Subscribed once Files is opened for this
  // project and kept warm afterwards (keepPreviousData avoids an empty flash
  // when switching back); a one-shot list, not polled.
  const fs = useSWR<FsList>(
    user && (view === "files" || filesSeenFor === id) ? `/projects/${id}/fs` : null,
    fetcher,
    { keepPreviousData: true },
  );

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
    if (pid !== id) {
      setView("mcp");
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

  const onDisconnect = async (kind: "github" | "slack" | "discord" | "liveagent" | "youtube") => {
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
          {banner && (
            <div className={"banner " + banner.kind}>
              <span>{banner.msg}</span>
              <button onClick={() => setBanner(null)} aria-label="Dismiss">
                ✕
              </button>
            </div>
          )}
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
          ) : view === "mcp" ? (
            <MCPView
              project={project.data}
              requests={mcpRequests.data ?? []}
              stats={mcpStats.data}
            />
          ) : view === "files" ? (
            <FilesView
              project={project.data}
              files={fs.data?.files ?? []}
              snapshotId={fs.data?.snapshot_id ?? null}
              loading={fs.isLoading}
              onReload={() => fs.mutate()}
            />
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
