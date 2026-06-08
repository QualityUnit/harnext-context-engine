"use client";

import { useState } from "react";
import type { McpRequest, McpStats, Project } from "@/lib/api";
import { rel } from "@/lib/sourceDisplay";
import { Icon } from "@/components/DashIcons";

// Pretty-print a stored request/response payload (object → JSON, string as-is).
function pretty(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// A one-line preview of the params for the collapsed table row.
function summarize(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((v) => summarize(v)).join(", ");
  if (typeof value === "object") {
    const parts = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`);
    return parts.join(" · ") || "—";
  }
  return String(value);
}

function CodeBlock({ label, body, tone }: { label: string; body: string; tone?: "err" }) {
  return (
    <div className="mcp-code">
      <div className="mcp-code-label">{label}</div>
      <pre className={"mcp-pre" + (tone === "err" ? " err" : "")}>
        <code>{body || "—"}</code>
      </pre>
    </div>
  );
}

function RequestRow({ r }: { r: McpRequest }) {
  const [open, setOpen] = useState(false);
  const ok = r.status === "ok";

  return (
    <div className={"mcp-row" + (open ? " open" : "")}>
      <button className="mcp-row-main" onClick={() => setOpen((o) => !o)}>
        <span className="mcp-chev" data-open={open}>
          <Icon.chevronR size={13} />
        </span>
        <span className="mcp-time">{rel(r.created_at)}</span>
        <span className="mcp-tool">{r.tool}</span>
        <span className="mcp-summary">{summarize(r.params)}</span>
        <span className={"pill sm " + (ok ? "ok" : "err")}>
          <span className="pill-dot" />
          {ok ? "ok" : "error"}
        </span>
        <span className="mcp-dur">{r.duration_ms.toLocaleString()}ms</span>
      </button>
      {open && (
        <div className="mcp-detail">
          <CodeBlock label="Request" body={pretty(r.params)} />
          {r.error ? (
            <CodeBlock label="Error" body={r.error} tone="err" />
          ) : (
            <CodeBlock label="Response" body={pretty(r.response)} />
          )}
        </div>
      )}
    </div>
  );
}

function StatsBar({ stats }: { stats?: McpStats }) {
  const bars = stats?.requests_per_day ?? Array(14).fill(0);
  const max = Math.max(...bars, 1);
  const tools = Object.entries(stats?.by_tool ?? {}).sort((a, b) => b[1] - a[1]);
  const errors = stats?.total_errors ?? 0;

  return (
    <div className="analytics">
      <div className="chart-card">
        <div className="chart-head">
          <div>
            <div className="chart-title">MCP requests</div>
            <div className="chart-sub">
              <b>{(stats?.total_requests ?? 0).toLocaleString()}</b> tool calls · last{" "}
              {stats?.days ?? 14} days
            </div>
          </div>
          {tools.length > 0 && (
            <div className="mcp-legend">
              {tools.map(([name, n]) => (
                <span key={name} className="mcp-legend-item">
                  <b>{n.toLocaleString()}</b> {name}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="chart" role="img" aria-label="MCP requests per day">
          {bars.map((v, i) => (
            <div
              key={i}
              className={"bar" + (i === bars.length - 1 ? " last" : "")}
              style={{ height: (v / max) * 100 + "%" }}
              title={`${v} requests`}
            />
          ))}
        </div>
        <div className="chart-x">
          <span>{stats?.days ?? 14}d ago</span>
          <span>{Math.round((stats?.days ?? 14) / 2)}d</span>
          <span>today</span>
        </div>
      </div>
      <div className="metric-col">
        <div className="metric big">
          <span className="metric-k">Total requests</span>
          <span className="metric-v">{(stats?.total_requests ?? 0).toLocaleString()}</span>
        </div>
        <div className="metric">
          <span className="metric-k">Errors</span>
          <span className="metric-v" style={errors > 0 ? { color: "var(--err)" } : undefined}>
            {errors.toLocaleString()}
          </span>
        </div>
        <div className="metric">
          <span className="metric-k">Avg latency</span>
          <span className="metric-v">
            {(stats?.avg_duration_ms ?? 0).toLocaleString()}
            <i>ms</i>
          </span>
        </div>
      </div>
    </div>
  );
}

export function MCPView({
  project,
  requests,
  stats,
}: {
  project: Project;
  requests: McpRequest[];
  stats?: McpStats;
}) {
  return (
    <div className="view">
      <div className="view-head">
        <div>
          <div className="crumb">
            {project.name}
            <span className="crumb-sep">/</span>
            <span>dashboard</span>
          </div>
          <h1 className="view-title">MCP server requests</h1>
          <p className="view-desc">
            Every tool call your agents make against <b>{project.name}</b>&apos;s MCP endpoint,
            with the full request and response. Volume over time is charted below.
          </p>
        </div>
      </div>

      <StatsBar stats={stats} />

      {requests.length === 0 ? (
        <div className="int-empty big">
          No MCP requests yet. Point your agent&apos;s harness at this project&apos;s MCP endpoint
          (see <b>Connect</b>) and tool calls will appear here in real time.
        </div>
      ) : (
        <div className="mcp-log">
          <div className="mcp-log-head">
            <span />
            <span>Time</span>
            <span>Tool</span>
            <span>Request</span>
            <span>Status</span>
            <span>Latency</span>
          </div>
          {requests.map((r) => (
            <RequestRow key={r.id} r={r} />
          ))}
        </div>
      )}
    </div>
  );
}
