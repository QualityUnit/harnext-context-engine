# MeaningGrid — Streaming Context Engine

An open-source **Context Management System (CMS)** for streaming AI agents. It
ingests heterogeneous events (GitHub, Slack, …), routes each onto a **fast** or
**batch** lane, and incorporates them into a living, per-organization **context
filesystem** maintained by a real coding agent (Claude Code / Codex) running over
[AgentFS](https://docs.turso.tech/agentfs/introduction). The org's context is
exposed to *external* agentic systems only through an **MCP server**.

This is the reference implementation for the thesis *"Open-Source Context Engine
for Streaming AI Agents."* The novel component is the **builder**: instead of a
fixed ETL pipeline, a stateless coding agent decides how to organize and
supersede knowledge in a filesystem.

## Architecture

```
GitHub / Slack
   │  connector → CloudEvents v1.0  (subject = entity key, mgtenant = org)
   ▼
apps/ingest ──► Kafka: cms.events.raw.v1
                       │
                       ▼
apps/classifier   rules floor + per-entity anomaly score; batch windowing
        │ FAST (per event, on arrival)          │ BATCH (per-entity window)
        ▼                                        ▼
   cms.events.fast.v1                       cms.events.batch.v1
        └──────────────┬─────────────────────────┘
                       ▼
apps/builder   (stateless, one writer per org)
   ensure org AgentFS → run the harness in the mounted FS to incorporate the
   event(s) → snapshot + raw-conversation log + build ledger
   stores:  AgentFS .db per org   +   conversation log   +   ledger/snapshots (SQLite)
                       │ reads the latest snapshot (consistent view)
                       ▼
apps/mcp   context_research · context_get_urls · context_update   ◄── external agents

apps/web   minimal UI to connect a source and watch it flow
```

- **One AgentFS `.db` per org** is the tenant boundary and the system of record.
  The builder mounts it via `agentfs exec`, the agent edits markdown files
  (`INDEX.md`, `entities/<subject>/{OVERVIEW,facts,timeline}.md`, `_meta/…`), and
  the result is snapshotted. A `git`-backed directory backend (used by the tests)
  is selectable via `AGENTFS_BACKEND`.
- **Harness-agnostic**: Claude Code (Claude Agent SDK, default) or Codex behind
  one interface; pick with `MEANINGGRID_HARNESS`. A `fake` harness runs the whole
  pipeline deterministically without an API key.
- **MCP is the only external surface.** External agents never touch Kafka or the
  store; they read a synthesized answer and write via an internal agent.

## Quick start

```bash
# 0. prerequisites: docker, uv, pnpm, and AgentFS
curl -fsSL https://agentfs.ai/install | bash      # installs `agentfs`
make install                                       # uv sync + pnpm install

# 1. infra + topics
make up && make topics

# 2. configure: copy .env.example → .env and set ANTHROPIC_API_KEY
#    (or set MEANINGGRID_HARNESS=fake to run without a key)

# 3. run each service in its own shell
make ingest      # FastAPI on :8000 (serves the UI)
make classifier  # fast/batch router
make builder     # AgentFS builder
make mcp         # MCP context server on :8765
make web         # UI on :3100
```

Then open the dashboard at **`http://localhost:3100`**:

1. **Sign in** — pick a username (demo auth, no password).
2. **Create a project** — this is a tenant; its id is the `mgtenant` used throughout.
3. **Connect a source** — *Connect GitHub* / *Connect Slack* (OAuth), or use
   *advanced: add manually* to add a public repo with no setup. Pick a repo/channel.
4. **Sync now** — events flow ingest → classify → build, and the *Recent events*
   and *Context builds* panels light up.

### OAuth setup (for the Connect buttons)

Register your own apps and put the credentials in `.env`:

- **GitHub** → an OAuth App with callback `http://localhost:8000/oauth/github/callback`
  → set `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET`.
- **Slack** → an app with redirect `http://localhost:8000/oauth/slack/callback` and
  scopes `channels:history,channels:read` → set `SLACK_OAUTH_CLIENT_ID` /
  `SLACK_OAUTH_CLIENT_SECRET`.

Without them, the *Connect* buttons are disabled and you use the manual path (a
public GitHub repo needs no token at all).

### Smoke test (no network, no API key)

```bash
MEANINGGRID_HARNESS=fake make classifier      # in one shell
MEANINGGRID_HARNESS=fake make builder         # in another
uv run --package meaninggrid-builder python scripts/smoke.py   # produce events
```

The 3 commits batch into one Context Unit; the P0 issue goes fast; the builder
incorporates both into `data/agentfs/.agentfs/acme.db`.

## Layout

| Path | What |
|------|------|
| `packages/shared` | CloudEvent envelope, ContextUnit, topics, DB models, session helpers |
| `apps/ingest` | source registry API + GitHub/Slack connectors → raw topic |
| `apps/classifier` | fast/batch routing (rules + anomaly) + batch windowing |
| `apps/builder` | the builder: AgentFS store, harness, build runner, Kafka consumers |
| `apps/mcp` | the external MCP surface (research / get_urls / update) |
| `apps/web` | minimal Next.js source-connection UI |

## Development

```bash
make test        # pytest (runs the git + agentfs backends)
make lint        # ruff
make typecheck   # pyright
```

## Status & scope (v1)

Working end to end: ingest → classify → build → MCP, with idempotency, per-org
single-writer serialization, snapshots, DLQ, and startup reconciliation.

Deferred (future work): HBOS/Flink anomaly detection, RQ3 sketch-based Context
Units, Docker sandbox, a bitemporal graph + RAG store, multi-node sharding,
webhooks, an encrypted token vault, and the SWE-bench-Live / ProAgentBench
evaluation harnesses. The prior Graphiti/FalkorDB v0 lives on branch
`archive/v0-graphiti`.
