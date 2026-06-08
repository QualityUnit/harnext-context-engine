"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import {
  api,
  fetcher,
  type Analytics,
  type Channel,
  type Health,
  type Project,
  type Repo,
  type Source,
} from "@/lib/api";
import { formatBytes, rel, sourceName, uiStatus, STATUS } from "@/lib/sourceDisplay";
import { Icon } from "@/components/DashIcons";

const errMsg = (e: unknown): string =>
  (e instanceof Error ? e.message : String(e)).replace(/^sync failed:\s*/i, "");

// Coerce a pasted GitHub URL / .git / owner-name-with-extra-path to "owner/name".
function normalizeRepo(raw: string): string {
  const s = raw
    .trim()
    .replace(/^https?:\/\//i, "")
    .replace(/^git@github\.com:/i, "")
    .replace(/^(www\.)?github\.com\//i, "")
    .replace(/\.git$/i, "");
  const parts = s.split("/").filter(Boolean);
  return parts.length >= 2 ? `${parts[0]}/${parts[1]}` : s.replace(/^\/+|\/+$/g, "");
}

// ---- source card -----------------------------------------------------------
function SourceCard({
  s,
  onSync,
  onRemove,
}: {
  s: Source;
  onSync: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const [menu, setMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const st = uiStatus(s);
  const meta = STATUS[st];
  const isGh = s.kind === "github";
  const watching = st === "live";

  return (
    <div className={"src-card " + st} ref={ref}>
      <div className="src-top">
        <span className={"src-ic " + s.kind}>{isGh ? <Icon.github size={18} /> : <Icon.slack size={18} />}</span>
        <div className="src-id">
          <span className="src-name">{sourceName(s)}</span>
          <span className="src-sub">
            {isGh ? <Icon.github size={11} /> : <Icon.slack size={11} />}
            {isGh ? "repository" : "channel"}
          </span>
        </div>
        <button className="icon-btn" onClick={() => setMenu((m) => !m)} title="Source actions">
          <Icon.dots size={16} />
        </button>
        {menu && (
          <div className="src-menu">
            <button
              onClick={() => {
                setMenu(false);
                onSync(s.id);
              }}
            >
              <Icon.sync size={14} />
              Sync now
            </button>
            <button
              className="danger"
              onClick={() => {
                setMenu(false);
                onRemove(s.id);
              }}
            >
              <Icon.trash size={14} />
              Remove
            </button>
          </div>
        )}
      </div>

      <div className="src-stats">
        <div className="stat">
          <span className="stat-v">{s.event_count.toLocaleString()}</span>
          <span className="stat-k">events indexed</span>
        </div>
        <div className="stat">
          <span className="stat-v">{rel(s.last_sync_at)}</span>
          <span className="stat-k">last sync</span>
        </div>
      </div>

      <div className="src-foot">
        <span className={"pill " + meta.cls}>
          <span className={"pill-dot" + (watching || st === "backfill" ? " spin" : "")} />
          {meta.label}
        </span>
        <span className="src-sync">
          {watching ? (
            <>
              <Icon.zap size={11} /> synced {rel(s.last_sync_at)}
            </>
          ) : st === "error" ? (
            (s.last_error || "sync failed").slice(0, 32)
          ) : st === "backfill" ? (
            "awaiting first sync…"
          ) : (
            "paused"
          )}
        </span>
      </div>
    </div>
  );
}

// ---- add-source modal ------------------------------------------------------
function AddSourceModal({
  project,
  onClose,
  onAdded,
}: {
  project: Project;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [step, setStep] = useState<"pick" | "github" | "slack">("pick");
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState("");
  const [channel, setChannel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  const channels = useSWR<Channel[]>(
    step === "slack" && project.slack_connected ? `/oauth/slack/channels?project_id=${project.id}` : null,
    fetcher,
  );
  const repos = useSWR<Repo[]>(
    step === "github" && project.github_connected ? `/oauth/github/repos?project_id=${project.id}` : null,
    fetcher,
  );
  const health = useSWR<Health>("/health", fetcher);
  const ghOauth = !!health.data?.oauth.github;
  const slackOauth = !!health.data?.oauth.slack;

  async function connect(kind: "github" | "slack", config: Record<string, unknown>, secret?: string | null) {
    setBusy(true);
    setErr(null);
    if (kind === "github" && typeof config.repo === "string") {
      config = { ...config, repo: normalizeRepo(config.repo) };
    }
    let src: Source;
    try {
      src = await api.createSource(project.id, kind, config, secret ?? null);
    } catch (e) {
      setErr(errMsg(e));
      setBusy(false);
      return;
    }
    // The first sync doubles as a connection test: a private repo with a
    // missing/wrong token (or a bad channel/token) fails here. Reject the
    // source instead of keeping a broken one.
    try {
      await api.syncSource(src.id);
    } catch (e) {
      await api.deleteSource(src.id).catch(() => {});
      setErr(errMsg(e));
      setBusy(false);
      return;
    }
    onAdded();
    onClose();
  }

  const title =
    step === "pick"
      ? "Add a context source"
      : step === "github"
        ? "Connect a GitHub repo"
        : "Connect a Slack channel";

  return (
    <div className="modal-wrap" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="icon-btn" onClick={onClose}>
            <Icon.x size={16} />
          </button>
        </div>

        {step === "pick" && (
          <div className="modal-body">
            <p className="modal-note">
              Sources stream events into this project&apos;s context grid and are served to your harness over MCP.
            </p>
            <div className="picker">
              <button className="pick-card" onClick={() => setStep("github")}>
                <span className="src-ic github lg">
                  <Icon.github size={22} />
                </span>
                <span>
                  <span className="pick-name">GitHub repository</span>
                  <span className="pick-sub">Commits, issues &amp; pull requests</span>
                </span>
                <span className="pick-go">
                  <Icon.chevronR size={15} />
                </span>
              </button>
              <button className="pick-card" onClick={() => setStep("slack")}>
                <span className="src-ic slack lg">
                  <Icon.slack size={22} />
                </span>
                <span>
                  <span className="pick-name">Slack channel</span>
                  <span className="pick-sub">Threads, decisions &amp; context</span>
                </span>
                <span className="pick-go">
                  <Icon.chevronR size={15} />
                </span>
              </button>
              <button className="pick-card soon" disabled>
                <span className="src-ic ghost lg">
                  <Icon.plus size={22} />
                </span>
                <span>
                  <span className="pick-name">Linear · Notion · Web</span>
                  <span className="pick-sub">Coming soon</span>
                </span>
              </button>
            </div>
          </div>
        )}

        {step === "github" && (
          <div className="modal-body">
            {project.github_connected && (repos.data?.length ?? 0) > 0 ? (
              <>
                <label className="field-label">Repository</label>
                <div className="field">
                  <span className="field-ic">
                    <Icon.github size={15} />
                  </span>
                  <select value={repo} onChange={(e) => setRepo(e.target.value)}>
                    <option value="">{repos.data ? "Select a repo…" : "Loading…"}</option>
                    {repos.data?.map((r) => (
                      <option key={r.full_name} value={r.full_name}>
                        {r.full_name}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="modal-note">Connected as @{project.github_login}. We index the default branch.</p>
              </>
            ) : (
              <>
                {ghOauth && (
                  <>
                    <button
                      className="btn primary lg connect-btn"
                      onClick={() => (window.location.href = api.oauthStartUrl("github", project.id))}
                    >
                      <Icon.github size={16} />
                      Connect with GitHub
                    </button>
                    <div className="or-sep">or add a repo with a token</div>
                  </>
                )}
                <label className="field-label">Repository</label>
                <div className="field">
                  <span className="field-ic">
                    <Icon.github size={15} />
                  </span>
                  <input
                    autoFocus
                    value={repo}
                    onChange={(e) => setRepo(e.target.value)}
                    placeholder="octocat/Hello-World  (or a GitHub URL)"
                  />
                </div>
                <label className="field-label" style={{ marginTop: 12 }}>
                  Access token <span style={{ color: "var(--tx-3)" }}>· only for private repos</span>
                </label>
                <div className="field">
                  <span className="field-ic">
                    <Icon.link size={15} />
                  </span>
                  <input
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="github_pat_… or ghp_…"
                  />
                </div>
                <p className="modal-note">
                  Public repos need no token. For a private repo, paste a read-only token —{" "}
                  <button className="help-toggle" onClick={() => setShowHelp((s) => !s)}>
                    {showHelp ? "hide steps" : "how to create one (least privilege)"}
                  </button>
                  .
                </p>
                {showHelp && (
                  <div className="token-help">
                    <b>Fine-grained token — read-only, this repo only</b>
                    <ol>
                      <li>
                        Open{" "}
                        <a
                          href="https://github.com/settings/personal-access-tokens/new"
                          target="_blank"
                          rel="noreferrer"
                        >
                          github.com/settings/personal-access-tokens/new
                        </a>
                        .
                      </li>
                      <li>
                        <b>Repository access</b> → <i>Only select repositories</i> → pick this repo.
                      </li>
                      <li>
                        <b>Permissions → Repository</b>: set <code>Contents</code>, <code>Issues</code>,{" "}
                        <code>Pull requests</code> and <code>Metadata</code> to <b>Read-only</b>.
                      </li>
                      <li>
                        <b>Generate token</b>, copy the <code>github_pat_…</code> value, paste it above.
                      </li>
                    </ol>
                    MeaningGrid only ever reads — it never writes to your repo.
                  </div>
                )}
              </>
            )}
            {err && <p className="modal-err">{err}</p>}
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setStep("pick")}>
                Back
              </button>
              <button
                className="btn primary"
                disabled={busy || !repo.trim()}
                onClick={() => connect("github", { repo: repo.trim() }, token.trim() || null)}
              >
                <Icon.plus size={15} />
                {busy ? "Connecting…" : "Connect repo"}
              </button>
            </div>
          </div>
        )}

        {step === "slack" && (
          <div className="modal-body">
            {project.slack_connected ? (
              <>
                <label className="field-label">Channel</label>
                <div className="field">
                  <span className="field-ic">
                    <Icon.slack size={15} />
                  </span>
                  <select value={channel} onChange={(e) => setChannel(e.target.value)}>
                    <option value="">{channels.data ? "Select a channel…" : "Loading…"}</option>
                    {channels.data?.map((c) => (
                      <option key={c.id} value={c.id}>
                        #{c.name}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="modal-note">
                  {project.slack_team_name ? `${project.slack_team_name} · ` : ""}last 90 days of history is
                  captured, then kept live.
                </p>
                {err && <p className="modal-err">{err}</p>}
                <div className="modal-actions">
                  <button className="btn ghost" onClick={() => setStep("pick")}>
                    Back
                  </button>
                  <button
                    className="btn primary"
                    disabled={busy || !channel}
                    onClick={() => {
                      const ch = channels.data?.find((c) => c.id === channel);
                      if (ch) connect("slack", { channel_id: ch.id, channel_name: ch.name });
                    }}
                  >
                    <Icon.plus size={15} />
                    {busy ? "Connecting…" : "Connect channel"}
                  </button>
                </div>
              </>
            ) : slackOauth ? (
              <>
                <p className="modal-note">
                  Authorize MeaningGrid to read channel history (read-only). You&apos;ll pick a channel
                  after connecting.
                </p>
                {err && <p className="modal-err">{err}</p>}
                <div className="modal-actions">
                  <button className="btn ghost" onClick={() => setStep("pick")}>
                    Back
                  </button>
                  <button
                    className="btn primary"
                    onClick={() => (window.location.href = api.oauthStartUrl("slack", project.id))}
                  >
                    <Icon.slack size={15} />
                    Connect with Slack
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="modal-note">
                  Slack isn&apos;t configured on this instance yet. An admin needs to set
                  <code className="ic"> SLACK_OAUTH_CLIENT_ID</code> /{" "}
                  <code className="ic">SLACK_OAUTH_CLIENT_SECRET</code> and restart.
                </p>
                <div className="modal-actions">
                  <button className="btn ghost" onClick={() => setStep("pick")}>
                    Back
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---- analytics -------------------------------------------------------------
function Analytics({ a }: { a?: Analytics }) {
  const bars = a?.events_per_day ?? Array(14).fill(0);
  const max = Math.max(...bars, 1);
  const [size, unit] = formatBytes(a?.context_bytes ?? 0);

  return (
    <div className="analytics">
      <div className="chart-card">
        <div className="chart-head">
          <div>
            <div className="chart-title">Events processed</div>
            <div className="chart-sub">
              <b>{(a?.total_events ?? 0).toLocaleString()}</b> events indexed · last {a?.days ?? 14} days
            </div>
          </div>
          <div className="range">
            <button>7d</button>
            <button className="active">14d</button>
          </div>
        </div>
        <div className="chart" role="img" aria-label="Events processed per day">
          {bars.map((v, i) => (
            <div
              key={i}
              className={"bar" + (i === bars.length - 1 ? " last" : "")}
              style={{ height: (v / max) * 100 + "%" }}
              title={`${v} events`}
            />
          ))}
        </div>
        <div className="chart-x">
          <span>{a?.days ?? 14}d ago</span>
          <span>{Math.round((a?.days ?? 14) / 2)}d</span>
          <span>today</span>
        </div>
      </div>
      <div className="metric-col">
        <div className="metric big">
          <span className="metric-k">Context size</span>
          <span className="metric-v">
            {size}
            <i>{unit}</i>
          </span>
        </div>
        <div className="metric">
          <span className="metric-k">Context builds</span>
          <span className="metric-v">{(a?.total_builds ?? 0).toLocaleString()}</span>
        </div>
        <div className="metric">
          <span className="metric-k">Sources · status</span>
          <span className="metric-v live">
            <span className="live-dot" />
            {a?.sources_live ?? 0} live
          </span>
        </div>
      </div>
    </div>
  );
}

// ---- view ------------------------------------------------------------------
export function SourcesView({
  project,
  sources,
  analytics,
  onSync,
  onRemove,
  onChanged,
}: {
  project: Project;
  sources: Source[];
  analytics?: Analytics;
  onSync: (id: string) => void;
  onRemove: (id: string) => void;
  onChanged: () => void;
}) {
  const [modal, setModal] = useState(false);

  return (
    <div className="view">
      <div className="view-head">
        <div>
          <div className="crumb">
            {project.name}
            <span className="crumb-sep">/</span>
            <span>sources</span>
          </div>
          <h1 className="view-title">Context sources</h1>
          <p className="view-desc">
            Connected sources stream events into <b>{project.name}</b>&apos;s grid continuously — no manual
            re-indexing. Whatever your agents query is always current.
          </p>
        </div>
        <button className="btn primary lg" onClick={() => setModal(true)}>
          <Icon.plus size={16} />
          Add source
        </button>
      </div>

      <Analytics a={analytics} />

      <div className="src-grid">
        {sources.map((s) => (
          <SourceCard key={s.id} s={s} onSync={onSync} onRemove={onRemove} />
        ))}
        <button className="src-card add" onClick={() => setModal(true)}>
          <span className="add-plus">
            <Icon.plus size={20} />
          </span>
          <span className="add-label">Add source</span>
          <span className="add-sub">GitHub repo or Slack channel</span>
        </button>
      </div>

      {modal && <AddSourceModal project={project} onClose={() => setModal(false)} onAdded={onChanged} />}
    </div>
  );
}
