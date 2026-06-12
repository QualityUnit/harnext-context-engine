"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  fetcher,
  type AgentEvent,
  type AgentSession,
  type AgentSessionDetail,
  type Project,
} from "@/lib/api";
import { rel } from "@/lib/sourceDisplay";
import { Icon } from "@/components/DashIcons";

// Pretty-print a value for the raw view / tool inputs (object → JSON, string as-is).
function pretty(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/* ── conversation rendering ─────────────────────────────────────────────
   Each stored event is a Claude-SDK stream-json envelope; render the ones a
   human cares about as readable turns. */

interface ContentBlock {
  type?: string;
  text?: string;
  thinking?: string;
  name?: string;
  input?: unknown;
  tool_use_id?: string;
  content?: unknown;
  is_error?: boolean;
}

function Turn({
  tone,
  label,
  children,
}: {
  tone: "assistant" | "tool" | "system" | "result";
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className={"sess-turn " + tone}>
      <div className="sess-turn-role">{label}</div>
      <div className="sess-turn-body">{children}</div>
    </div>
  );
}

function AssistantTurn({ message }: { message: { content?: ContentBlock[] } }) {
  const blocks = message.content ?? [];
  return (
    <Turn tone="assistant" label="Assistant">
      {blocks.map((b, i) => {
        if (b.type === "text" && b.text) return <div key={i} className="sess-text">{b.text}</div>;
        if (b.type === "thinking" && b.thinking)
          return (
            <div key={i} className="sess-think">
              <span className="sess-think-k">thinking</span>
              {b.thinking}
            </div>
          );
        if (b.type === "tool_use")
          return (
            <div key={i} className="sess-tool">
              <div className="sess-tool-head">
                <Icon.terminal size={12} /> {b.name}
              </div>
              {b.input != null && <pre className="sess-pre"><code>{pretty(b.input)}</code></pre>}
            </div>
          );
        return null;
      })}
    </Turn>
  );
}

function ToolResultTurn({ message }: { message: { content?: ContentBlock[] } }) {
  const block = (message.content ?? [])[0];
  const err = block?.is_error;
  return (
    <Turn tone="tool" label={err ? "Tool result · error" : "Tool result"}>
      <pre className={"sess-pre" + (err ? " err" : "")}>
        <code>{typeof block?.content === "string" ? block.content : pretty(block?.content)}</code>
      </pre>
    </Turn>
  );
}

function ResultTurn({ payload }: { payload: Record<string, unknown> }) {
  const ok = payload.is_error !== true;
  const usage = (payload.usage ?? {}) as Record<string, number>;
  const cost = payload.total_cost_usd as number | undefined;
  return (
    <Turn tone="result" label="Result">
      <div className="sess-result-row">
        <span className={"pill sm " + (ok ? "ok" : "err")}>
          <span className="pill-dot" />
          {String(payload.subtype ?? (ok ? "success" : "error"))}
        </span>
        {typeof payload.num_turns === "number" && (
          <span className="sess-result-stat">{payload.num_turns} turns</span>
        )}
        {(usage.input_tokens != null || usage.output_tokens != null) && (
          <span className="sess-result-stat">
            {(usage.input_tokens ?? 0).toLocaleString()} in ·{" "}
            {(usage.output_tokens ?? 0).toLocaleString()} out
          </span>
        )}
        {typeof cost === "number" && cost > 0 && (
          <span className="sess-result-stat">${cost.toFixed(4)}</span>
        )}
      </div>
    </Turn>
  );
}

function ConversationTurn({ event }: { event: AgentEvent }) {
  const p = (event.payload ?? {}) as Record<string, unknown>;
  const message = p.message as { role?: string; content?: ContentBlock[] } | undefined;
  if (event.type === "assistant" && message) return <AssistantTurn message={message} />;
  if (event.type === "user" && message) return <ToolResultTurn message={message} />;
  if (event.type === "result") return <ResultTurn payload={p} />;
  return null; // system/init is surfaced in the detail header, not the stream
}

/* ── detail panel ───────────────────────────────────────────────────── */

function SessionDetail({ projectId, session }: { projectId: string; session: AgentSession }) {
  const [raw, setRaw] = useState(false);
  const { data, isLoading } = useSWR<AgentSessionDetail>(
    `/projects/${projectId}/agent-sessions/${session.id}`,
    fetcher,
    { keepPreviousData: false, refreshInterval: session.status === "open" ? 4000 : 0 },
  );
  const events = data?.events ?? [];

  return (
    <div className="sess-detail">
      <div className="sess-detail-head">
        <div>
          <div className="sess-detail-title">{session.title || session.client_session_id}</div>
          <div className="sess-detail-meta">
            <span className="sess-tag">{session.harness}</span>
            {session.model && <span className="sess-tag">{session.model}</span>}
            <span className={"pill sm " + (session.status === "closed" ? "ok" : "")}>
              <span className="pill-dot" />
              {session.status === "closed" ? session.stop_reason || "closed" : "open"}
            </span>
            <span className="sess-detail-time">{rel(session.started_at)}</span>
          </div>
          {session.cwd && <div className="sess-detail-cwd">{session.cwd}</div>}
        </div>
        <div className="sess-modes">
          <button className={"sess-mode" + (!raw ? " active" : "")} onClick={() => setRaw(false)}>
            Conversation
          </button>
          <button className={"sess-mode" + (raw ? " active" : "")} onClick={() => setRaw(true)}>
            Raw
          </button>
        </div>
      </div>

      {isLoading && events.length === 0 ? (
        <div className="int-empty">Loading transcript…</div>
      ) : raw ? (
        <div className="sess-convo">
          {events.map((e) => (
            <div key={e.seq} className="sess-raw">
              <div className="mcp-code-label">{`#${e.seq} · ${e.type}`}</div>
              <pre className="sess-pre"><code>{pretty(e.payload)}</code></pre>
            </div>
          ))}
        </div>
      ) : (
        <div className="sess-convo">
          {events.map((e) => (
            <ConversationTurn key={e.seq} event={e} />
          ))}
          {events.length === 0 && <div className="int-empty">No turns recorded yet.</div>}
        </div>
      )}
    </div>
  );
}

/* ── list + shell ───────────────────────────────────────────────────── */

function SessionItem({
  s,
  active,
  onSelect,
}: {
  s: AgentSession;
  active: boolean;
  onSelect: () => void;
}) {
  const closed = s.status === "closed";
  return (
    <button className={"sess-item" + (active ? " active" : "")} onClick={onSelect}>
      <div className="sess-item-title">{s.title || s.client_session_id}</div>
      <div className="sess-item-meta">
        <span className="sess-tag">{s.harness}</span>
        {s.model && <span className="sess-item-model">{s.model}</span>}
      </div>
      <div className="sess-item-foot">
        <span className={"pill sm " + (closed ? "ok" : "")}>
          <span className="pill-dot" />
          {closed ? s.stop_reason || "closed" : "open"}
        </span>
        <span className="sess-item-when">{rel(s.started_at)}</span>
        <span className="sess-item-turns">{s.event_count} turns</span>
      </div>
    </button>
  );
}

export function SessionsView({
  project,
  sessions,
}: {
  project: Project;
  sessions: AgentSession[];
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Default to the newest session; keep the selection valid as the list refreshes.
  useEffect(() => {
    if (sessions.length === 0) {
      setSelectedId(null);
    } else if (!selectedId || !sessions.some((s) => s.id === selectedId)) {
      setSelectedId(sessions[0].id);
    }
  }, [sessions, selectedId]);

  const selected = useMemo(
    () => sessions.find((s) => s.id === selectedId) ?? null,
    [sessions, selectedId],
  );

  return (
    <div className="view">
      <div className="view-head">
        <div>
          <div className="crumb">
            {project.name}
            <span className="crumb-sep">/</span>
            <span>sessions</span>
          </div>
          <h1 className="view-title">Sessions</h1>
          <p className="view-desc">
            Every conversation your harness (recommended: <b>harnext</b>) pushes to{" "}
            <b>{project.name}</b>. Pick a session on the left to read its full transcript.
          </p>
        </div>
      </div>

      {sessions.length === 0 ? (
        <div className="int-empty big">
          No sessions yet. Connect a harness with <code>harnext connect</code>, then every
          conversation streams in here in real time.
        </div>
      ) : (
        <div className="sess-wrap">
          <div className="sess-list">
            {sessions.map((s) => (
              <SessionItem
                key={s.id}
                s={s}
                active={s.id === selectedId}
                onSelect={() => setSelectedId(s.id)}
              />
            ))}
          </div>
          {selected ? (
            <SessionDetail key={selected.id} projectId={project.id} session={selected} />
          ) : (
            <div className="sess-detail sess-detail-empty">
              <div className="int-empty">Select a session to view its conversation.</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
