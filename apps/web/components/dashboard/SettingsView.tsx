"use client";

import { useState } from "react";
import type { Project, Source } from "@/lib/api";
import { sourceName, uiStatus, STATUS } from "@/lib/sourceDisplay";
import { Icon } from "@/components/DashIcons";

function SetRow({ label, desc, children }: { label: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="set-row">
      <div className="set-rl">
        <div className="set-label">{label}</div>
        {desc && <div className="set-desc">{desc}</div>}
      </div>
      <div className="set-rc">{children}</div>
    </div>
  );
}

function GeneralSettings({
  project,
  onRename,
  onDelete,
}: {
  project: Project;
  onRename: (name: string) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(project.name);
  const commit = () => {
    const v = name.trim();
    if (v && v !== project.name) onRename(v);
  };
  return (
    <div className="set-stack">
      <div className="set-card">
        <div className="set-card-head">
          <Icon.settings size={15} />
          <h3>Project</h3>
        </div>
        <SetRow label="Project name" desc="Shown in the switcher and used as the MCP scope.">
          <div className="field sm">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
            />
          </div>
        </SetRow>
      </div>

      <div className="set-card danger">
        <div className="set-card-head">
          <Icon.alert size={15} />
          <h3>Danger zone</h3>
        </div>
        <SetRow
          label="Delete project"
          desc="Permanently removes this grid, its context filesystem and all source links."
        >
          <button
            className="btn danger"
            onClick={() => {
              if (confirm(`Delete "${project.name}"? This cannot be undone.`)) onDelete();
            }}
          >
            Delete project
          </button>
        </SetRow>
      </div>
    </div>
  );
}

const PROVIDERS = {
  github: { name: "GitHub", noun: "repositories", scope: "repo · read" },
  slack: { name: "Slack", noun: "channels", scope: "channels:history" },
  discord: { name: "Discord", noun: "channels", scope: "Read Message History" },
  youtube: { name: "YouTube", noun: "channels", scope: "public captions" },
} as const;

type ProviderKind = keyof typeof PROVIDERS;

function IntegrationCard({
  kind,
  account,
  sources,
  onRemove,
  onDisconnect,
}: {
  kind: ProviderKind;
  account: string;
  sources: Source[];
  onRemove: (id: string) => void;
  onDisconnect: (kind: ProviderKind) => void;
}) {
  const p = PROVIDERS[kind];
  const TypeIcon =
    kind === "github"
      ? Icon.github
      : kind === "slack"
        ? Icon.slack
        : kind === "discord"
          ? Icon.discord
          : Icon.youtube;
  return (
    <div className="int-card">
      <div className="int-head">
        <span className={"src-ic " + kind + " lg"}>
          <TypeIcon size={20} />
        </span>
        <div className="int-meta">
          <div className="int-name">
            {p.name}
            <span className="pill ok sm">
              <span className="pill-dot" />
              Connected
            </span>
          </div>
          <div className="int-sub">
            {account ? `${account} · ` : ""}
            {sources.length} {p.noun} · scope <code className="ic">{p.scope}</code>
          </div>
        </div>
        <button
          className="btn ghost danger-h"
          onClick={() => {
            if (confirm(`Disconnect ${p.name}? This revokes the token and removes its ${sources.length} source(s).`))
              onDisconnect(kind);
          }}
        >
          <Icon.unlink size={14} />
          Disconnect
        </button>
      </div>
      <div className="int-list">
        {sources.length === 0 && <div className="int-empty">No {p.noun} connected.</div>}
        {sources.map((s) => {
          const st = uiStatus(s);
          const meta = STATUS[st];
          return (
            <div key={s.id} className="int-src">
              <span className="int-src-ic">
                <TypeIcon size={13} />
              </span>
              <span className="int-src-name">{sourceName(s)}</span>
              <span className="int-src-sub">{s.event_count.toLocaleString()} events</span>
              <span className={"pill sm " + meta.cls}>
                <span className="pill-dot" />
                {meta.label}
              </span>
              <button className="icon-btn danger-h" title="Remove source" onClick={() => onRemove(s.id)}>
                <Icon.trash size={15} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function IntegrationSettings({
  project,
  sources,
  onRemove,
  onDisconnect,
}: {
  project: Project;
  sources: Source[];
  onRemove: (id: string) => void;
  onDisconnect: (kind: ProviderKind) => void;
}) {
  const gh = sources.filter((s) => s.kind === "github");
  const sl = sources.filter((s) => s.kind === "slack");
  const dc = sources.filter((s) => s.kind === "discord");
  const yt = sources.filter((s) => s.kind === "youtube");
  const showGh = project.github_connected || gh.length > 0;
  const showSl = project.slack_connected || sl.length > 0;
  const showDc = project.discord_connected || dc.length > 0;
  // YouTube has no OAuth "connected" state — surface it once it has sources.
  const showYt = yt.length > 0;

  return (
    <div className="set-stack">
      <div className="set-intro">
        Connected providers feed this project. Disconnect a provider to revoke its token and remove all of its
        sources, or remove sources individually.
      </div>

      {showGh && (
        <IntegrationCard
          kind="github"
          account={project.github_login ? `@${project.github_login}` : ""}
          sources={gh}
          onRemove={onRemove}
          onDisconnect={onDisconnect}
        />
      )}
      {showSl && (
        <IntegrationCard
          kind="slack"
          account={project.slack_team_name ?? ""}
          sources={sl}
          onRemove={onRemove}
          onDisconnect={onDisconnect}
        />
      )}
      {showDc && (
        <IntegrationCard
          kind="discord"
          account={project.discord_guild_name ?? ""}
          sources={dc}
          onRemove={onRemove}
          onDisconnect={onDisconnect}
        />
      )}
      {showYt && (
        <IntegrationCard
          kind="youtube"
          account=""
          sources={yt}
          onRemove={onRemove}
          onDisconnect={onDisconnect}
        />
      )}
      {!showGh && !showSl && !showDc && !showYt && (
        <div className="int-empty big">
          No integrations connected. Add a source from the Sources view to connect GitHub, Slack,
          Discord or YouTube.
        </div>
      )}

      <div className="set-card-head sub">
        <Icon.plus size={14} />
        Available connectors
      </div>
      <div className="avail">
        {[
          ["Linear", "Issues & projects"],
          ["Notion", "Docs & wikis"],
          ["Google Drive", "Files & folders"],
          ["Web", "Crawl any URL"],
        ].map(([n, d]) => (
          <div key={n} className="avail-card">
            <span className="src-ic ghost">
              <Icon.plus size={16} />
            </span>
            <div className="avail-meta">
              <div className="avail-name">{n}</div>
              <div className="avail-sub">{d}</div>
            </div>
            <span className="soon-tag">Soon</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SettingsView({
  project,
  sources,
  onRename,
  onRemoveSource,
  onDisconnect,
  onDelete,
}: {
  project: Project;
  sources: Source[];
  onRename: (name: string) => void;
  onRemoveSource: (id: string) => void;
  onDisconnect: (kind: ProviderKind) => void;
  onDelete: () => void;
}) {
  const [tab, setTab] = useState<"general" | "integrations">("general");
  return (
    <div className="view">
      <div className="view-head">
        <div>
          <div className="crumb">
            {project.name}
            <span className="crumb-sep">/</span>
            <span>settings</span>
          </div>
          <h1 className="view-title">Settings</h1>
          <p className="view-desc">
            Manage <b>{project.name}</b>&apos;s general configuration and connected integrations.
          </p>
        </div>
      </div>

      <div className="tabs">
        <button className={"tab" + (tab === "general" ? " active" : "")} onClick={() => setTab("general")}>
          <Icon.settings size={14} />
          General
        </button>
        <button
          className={"tab" + (tab === "integrations" ? " active" : "")}
          onClick={() => setTab("integrations")}
        >
          <Icon.link size={14} />
          Integrations
        </button>
      </div>

      {tab === "general" ? (
        <GeneralSettings project={project} onRename={onRename} onDelete={onDelete} />
      ) : (
        <IntegrationSettings
          project={project}
          sources={sources}
          onRemove={onRemoveSource}
          onDisconnect={onDisconnect}
        />
      )}
    </div>
  );
}
