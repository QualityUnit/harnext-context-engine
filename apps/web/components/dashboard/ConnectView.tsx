"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, type McpInfo, type Project, type Source } from "@/lib/api";
import { Icon } from "@/components/DashIcons";

function Copyable({ code, label }: { code: string; label?: string }) {
  const [done, setDone] = useState(false);
  const copy = () => {
    try {
      navigator.clipboard.writeText(code);
    } catch {
      /* clipboard may be unavailable over http */
    }
    setDone(true);
    setTimeout(() => setDone(false), 1400);
  };
  return (
    <div className="code">
      {label && (
        <div className="code-bar">
          <span className="code-lang">{label}</span>
          <button className="code-copy" onClick={copy}>
            {done ? <Icon.check size={13} /> : <Icon.copy size={13} />}
            {done ? "Copied" : "Copy"}
          </button>
        </div>
      )}
      <pre>
        {!label && (
          <button className="code-copy float" onClick={copy}>
            {done ? <Icon.check size={13} /> : <Icon.copy size={13} />}
          </button>
        )}
        <code>{code}</code>
      </pre>
    </div>
  );
}

function Step({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  return (
    <div className="step">
      <div className="step-n">{n}</div>
      <div className="step-body">
        <h4 className="step-title">{title}</h4>
        {children}
      </div>
    </div>
  );
}

const HARNESSES = ["Claude Code", "Codex", "Cursor", "Generic MCP / CLI"];

export function ConnectView({ project, sources }: { project: Project; sources: Source[] }) {
  const [tab, setTab] = useState("Claude Code");
  const [revealed, setRevealed] = useState(false);
  const { data: mcp } = useSWR<McpInfo>(`/projects/${project.id}/mcp`, fetcher);

  const endpoint = mcp?.endpoint ?? "http://localhost:8765/mcp";
  const token = mcp?.token ?? "";
  const tokenShown = token ? (revealed ? token : `${token.slice(0, 12)}…${token.slice(-6)}`) : "loading…";
  const n = sources.length;

  // One command/config per harness — same endpoint, project-scoped bearer token.
  const claudeCmd = `claude mcp add --transport http meaninggrid \\\n  ${endpoint} \\\n  --header "Authorization: Bearer ${token}"`;
  const codexToml = `[mcp_servers.meaninggrid]\nurl = "${endpoint}"\nhttp_headers = { Authorization = "Bearer ${token}" }`;
  const jsonCfg = (transport: boolean) =>
    `{\n  "mcpServers": {\n    "meaninggrid": {\n${transport ? '      "transport": "http",\n' : ""}      "url": "${endpoint}",\n      "headers": { "Authorization": "Bearer ${token}" }\n    }\n  }\n}`;

  return (
    <div className="view">
      <div className="view-head">
        <div>
          <div className="crumb">
            {project.name}
            <span className="crumb-sep">/</span>
            <span>connect</span>
          </div>
          <h1 className="view-title">Connect a harness</h1>
          <p className="view-desc">
            Point your agent at <b>{project.name}</b>&apos;s context grid over MCP. One always-on endpoint;
            the bearer token below scopes the connection to this project and exposes{" "}
            <code>context_research</code>, <code>context_get_urls</code> and <code>context_update</code>.
          </p>
        </div>
      </div>

      <div className="endpoint">
        <div className="ep-row">
          <span className="ep-k">
            <Icon.link size={13} />
            MCP endpoint
          </span>
          <code className="ep-v">{endpoint}</code>
          <span className="ep-tag">3 tools</span>
        </div>
        <div className="ep-row">
          <span className="ep-k">
            <Icon.zap size={13} />
            Bearer token
          </span>
          <code className="ep-v">{tokenShown}</code>
          <button
            className="icon-btn"
            title={revealed ? "Hide" : "Reveal"}
            onClick={() => setRevealed((r) => !r)}
          >
            <Icon.settings size={14} />
          </button>
          <button
            className="icon-btn"
            title="Copy token"
            onClick={() => token && navigator.clipboard?.writeText(token).catch(() => {})}
          >
            <Icon.copy size={14} />
          </button>
        </div>
      </div>

      <div className="tabs">
        {HARNESSES.map((h) => (
          <button key={h} className={"tab" + (tab === h ? " active" : "")} onClick={() => setTab(h)}>
            <Icon.terminal size={14} />
            {h}
          </button>
        ))}
      </div>

      <div className="steps">
        {tab === "Claude Code" && (
          <>
            <Step n="1" title="Add MeaningGrid as an MCP server">
              <p className="step-p">
                One command, run in your repo root — Claude Code writes it to <code className="ic">.mcp.json</code>.
              </p>
              <Copyable label="bash" code={claudeCmd} />
            </Step>
            <Step n="2" title="Verify and use it">
              <p className="step-p">
                <code className="ic">claude mcp list</code> should show <b>meaninggrid</b> connected with 3
                tools{n ? ` over ${n} source${n === 1 ? "" : "s"}` : ""}. Then just ask:
              </p>
              <Copyable code={`> why did we move incidents off the legacy queue?\n  ↳ context_research(question="…")`} />
            </Step>
          </>
        )}

        {tab === "Codex" && (
          <Step n="1" title="Add the server to your Codex config">
            <p className="step-p">
              Append to <code className="ic">~/.codex/config.toml</code> — the header carries this project&apos;s
              token.
            </p>
            <Copyable label="toml" code={codexToml} />
          </Step>
        )}

        {tab === "Cursor" && (
          <Step n="1" title="Add the server to Cursor">
            <p className="step-p">
              Create <code className="ic">.cursor/mcp.json</code> in your project (or edit the global one in
              Settings → MCP), then toggle <b>meaninggrid</b> on.
            </p>
            <Copyable label="json" code={jsonCfg(false)} />
          </Step>
        )}

        {tab === "Generic MCP / CLI" && (
          <Step n="1" title="Any MCP-compatible client">
            <p className="step-p">
              MeaningGrid speaks the streamable-HTTP MCP transport with a bearer token. Works with Cursor,
              Continue, Cline and custom agents.
            </p>
            <Copyable label="json" code={jsonCfg(true)} />
          </Step>
        )}
      </div>
    </div>
  );
}
