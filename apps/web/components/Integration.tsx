"use client";

import { useState } from "react";
import useSWR from "swr";
import { api, fetcher, type Channel, type Project, type Repo } from "@/lib/api";
import { Badge, Button, Card, Field, inputCls } from "@/components/ui";

export function Integration({
  provider,
  project,
  oauthConfigured,
  onChanged,
}: {
  provider: "github" | "slack";
  project: Project;
  oauthConfigured: boolean;
  onChanged: () => void;
}) {
  const label = provider === "github" ? "GitHub" : "Slack";
  const connected = provider === "github" ? project.github_connected : project.slack_connected;
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const title = (
    <span className="flex items-center gap-2">
      {label}
      <Badge value={connected ? "connected" : "not connected"} />
    </span>
  );

  return (
    <Card
      title={title}
      action={
        !connected ? (
          <Button
            variant="ghost"
            disabled={!oauthConfigured}
            onClick={() => (window.location.href = api.oauthStartUrl(provider, project.id))}
          >
            {oauthConfigured ? `Connect ${label}` : "OAuth not configured"}
          </Button>
        ) : (
          <span className="text-xs text-neutral-400">
            {provider === "github"
              ? `as @${project.github_login}`
              : project.slack_team_name}
          </span>
        )
      }
    >
      <div className="flex flex-col gap-4">
        {connected ? (
          provider === "github" ? (
            <RepoPicker projectId={project.id} onAdded={onChanged} setError={setError} />
          ) : (
            <ChannelPicker projectId={project.id} onAdded={onChanged} setError={setError} />
          )
        ) : (
          <div className="text-sm text-neutral-400">
            Connect {label} to pull its events into this project.
            <button
              className="ml-2 text-neutral-300 underline"
              onClick={() => setAdvanced((v) => !v)}
            >
              {advanced ? "hide" : "advanced: add manually"}
            </button>
          </div>
        )}

        {!connected && advanced && (
          <ManualForm provider={provider} projectId={project.id} onAdded={onChanged} setError={setError} />
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>
    </Card>
  );
}

function RepoPicker({
  projectId,
  onAdded,
  setError,
}: {
  projectId: string;
  onAdded: () => void;
  setError: (s: string | null) => void;
}) {
  const { data: repos, error } = useSWR<Repo[]>(`/oauth/github/repos?project_id=${projectId}`, fetcher);
  const [repo, setRepo] = useState("");
  const [busy, setBusy] = useState(false);

  async function add() {
    if (!repo) return;
    setBusy(true);
    setError(null);
    try {
      await api.createSource(projectId, "github", { repo });
      setRepo("");
      onAdded();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="text-sm text-red-400">Could not list repos: {String(error)}</p>;
  return (
    <div className="flex items-end gap-3">
      <div className="flex-1">
        <Field label="Repository">
          <select className={inputCls} value={repo} onChange={(e) => setRepo(e.target.value)}>
            <option value="">{repos ? "Select a repo…" : "Loading…"}</option>
            {repos?.map((r) => (
              <option key={r.full_name} value={r.full_name}>
                {r.full_name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Button onClick={add} disabled={busy || !repo}>
        {busy ? "Adding…" : "Add repo"}
      </Button>
    </div>
  );
}

function ChannelPicker({
  projectId,
  onAdded,
  setError,
}: {
  projectId: string;
  onAdded: () => void;
  setError: (s: string | null) => void;
}) {
  const { data: channels, error } = useSWR<Channel[]>(
    `/oauth/slack/channels?project_id=${projectId}`,
    fetcher,
  );
  const [channel, setChannel] = useState("");
  const [busy, setBusy] = useState(false);

  async function add() {
    const ch = channels?.find((c) => c.id === channel);
    if (!ch) return;
    setBusy(true);
    setError(null);
    try {
      await api.createSource(projectId, "slack", { channel_id: ch.id, channel_name: ch.name });
      setChannel("");
      onAdded();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="text-sm text-red-400">Could not list channels: {String(error)}</p>;
  return (
    <div className="flex items-end gap-3">
      <div className="flex-1">
        <Field label="Channel">
          <select className={inputCls} value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">{channels ? "Select a channel…" : "Loading…"}</option>
            {channels?.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Button onClick={add} disabled={busy || !channel}>
        {busy ? "Adding…" : "Add channel"}
      </Button>
    </div>
  );
}

function ManualForm({
  provider,
  projectId,
  onAdded,
  setError,
}: {
  provider: "github" | "slack";
  projectId: string;
  onAdded: () => void;
  setError: (s: string | null) => void;
}) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      if (provider === "github") {
        await api.createSource(projectId, "github", { repo: a }, token || null);
      } else {
        await api.createSource(projectId, "slack", { channel_id: a, channel_name: b || a }, token || null);
      }
      setA("");
      setB("");
      setToken("");
      onAdded();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-neutral-800 p-3">
      {provider === "github" ? (
        <Field label="Public repo (owner/name)">
          <input className={inputCls} value={a} onChange={(e) => setA(e.target.value)} placeholder="octocat/Hello-World" />
        </Field>
      ) : (
        <>
          <Field label="Channel ID">
            <input className={inputCls} value={a} onChange={(e) => setA(e.target.value)} placeholder="C0123456" />
          </Field>
          <Field label="Channel name">
            <input className={inputCls} value={b} onChange={(e) => setB(e.target.value)} placeholder="general" />
          </Field>
        </>
      )}
      <Field label={provider === "github" ? "Token (optional for public repos)" : "Slack bot token"}>
        <input className={inputCls} type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder={provider === "slack" ? "xoxb-…" : "ghp_… (optional)"} />
      </Field>
      <div>
        <Button onClick={add} disabled={busy || !a}>
          {busy ? "Adding…" : "Add source"}
        </Button>
      </div>
    </div>
  );
}
