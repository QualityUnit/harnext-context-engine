"use client";

import { useState } from "react";
import type { Project, Source } from "@/lib/api";
import { Icon } from "@/components/DashIcons";

const MCP_BASE = process.env.NEXT_PUBLIC_MCP_BASE_URL ?? "http://localhost:8765/mcp";

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
  const endpoint = MCP_BASE;
  const n = sources.length;

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
            Point your agent at <b>{project.name}</b>&apos;s context grid over MCP. Same endpoint, every harness —
            it exposes <code>context_research</code>, <code>context_get_urls</code> and <code>context_update</code>.
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
            <Icon.sources size={13} />
            Project scope
          </span>
          <code className="ep-v">{project.id}</code>
          <span className="ep-tag">org</span>
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
            <Step n="1" title="Launch the grid's MCP server for this project">
              <p className="step-p">
                The server is one process per project, scoped by <code className="ic">MEANINGGRID_ORG_ID</code>.
              </p>
              <Copyable label="bash" code={`MEANINGGRID_ORG_ID=${project.id} uv run meaninggrid-mcp`} />
            </Step>
            <Step n="2" title="Register it with Claude Code">
              <p className="step-p">
                Run this in your repo root — Claude Code writes it to <code className="ic">.mcp.json</code>.
              </p>
              <Copyable label="bash" code={`claude mcp add --transport http meaninggrid ${endpoint}`} />
            </Step>
            <Step n="3" title="Ask across your context">
              <p className="step-p">
                List tools to confirm (<code className="ic">claude mcp list</code> → {n} source
                {n === 1 ? "" : "s"}), then query the grid.
              </p>
              <Copyable code={`> why did we move incidents off the legacy queue?\n  ↳ context_research(question="…")`} />
            </Step>
          </>
        )}

        {tab === "Codex" && (
          <>
            <Step n="1" title="Launch the MCP server">
              <Copyable label="bash" code={`MEANINGGRID_ORG_ID=${project.id} uv run meaninggrid-mcp`} />
            </Step>
            <Step n="2" title="Add it to your Codex config">
              <p className="step-p">
                Append to <code className="ic">~/.codex/config.toml</code>.
              </p>
              <Copyable
                label="toml"
                code={`[mcp_servers.meaninggrid]\nurl = "${endpoint}"\ntransport = "http"`}
              />
            </Step>
            <Step n="3" title="Reference it in a task">
              <Copyable code={`codex "use the meaninggrid context for ${project.name}"`} />
            </Step>
          </>
        )}

        {tab === "Cursor" && (
          <>
            <Step n="1" title="Launch the MCP server">
              <Copyable label="bash" code={`MEANINGGRID_ORG_ID=${project.id} uv run meaninggrid-mcp`} />
            </Step>
            <Step n="2" title="Add the server to Cursor">
              <p className="step-p">
                Create <code className="ic">.cursor/mcp.json</code> in your project (or edit the global one in
                Settings → MCP).
              </p>
              <Copyable
                label="json"
                code={`{\n  "mcpServers": {\n    "meaninggrid": {\n      "url": "${endpoint}"\n    }\n  }\n}`}
              />
            </Step>
            <Step n="3" title="Use it from the Agent">
              <p className="step-p">In Agent mode (⌘I) the grid&apos;s retrievers are available as tools automatically.</p>
              <Copyable code={`@meaninggrid where do we validate webhook signatures?`} />
            </Step>
          </>
        )}

        {tab === "Generic MCP / CLI" && (
          <>
            <Step n="1" title="Any MCP-compatible client">
              <p className="step-p">
                MeaningGrid speaks the streamable-HTTP MCP transport. Works with Cursor, Continue, Cline and custom
                agents.
              </p>
              <Copyable
                label="json"
                code={`{\n  "mcpServers": {\n    "meaninggrid": {\n      "transport": "http",\n      "url": "${endpoint}"\n    }\n  }\n}`}
              />
            </Step>
            <Step n="2" title="Self-host the whole engine">
              <p className="step-p">It&apos;s open source — run the full pipeline locally.</p>
              <Copyable
                label="bash"
                code={`# ingest · classifier · builder · mcp\nmake up\nMEANINGGRID_ORG_ID=${project.id} uv run meaninggrid-mcp`}
              />
            </Step>
          </>
        )}
      </div>
    </div>
  );
}
