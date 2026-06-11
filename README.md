# Harnext — Streaming Context Engine

An open-source **Context Management System (CMS)** for streaming AI agents. It
ingests heterogeneous events (GitHub, Slack, Discord, …), routes each onto a **fast** or
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
GitHub / Slack / Discord / LiveAgent / YouTube / Website (sitemap)
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
  one interface; pick with `HARNEXT_HARNESS`. A `fake` harness runs the whole
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
#    (or set HARNEXT_HARNESS=fake to run without a key)

# 3. run each service in its own shell
make ingest      # FastAPI on :8000 (serves the UI)
make classifier  # fast/batch router
make builder     # AgentFS builder
make mcp         # MCP context server on :8765
make web         # UI on :3100
make worker      # Celery worker — runs source polls (needs Redis from `make up`)
make beat        # Celery beat — schedules polls (ticks every minute; sources poll hourly)
```

Then open the dashboard at **`http://localhost:3100`**:

1. **Sign in** — register with email + password, or **Continue with Google**. Sessions
   are JWTs; the API routes are scoped to the logged-in user.
2. **Create a project** — this is a tenant; its id is the `mgtenant` used throughout.
3. **Connect a source** — *Connect GitHub* / *Connect Slack* / *Connect Discord* (OAuth),
   or use *advanced: add manually* to add a public repo with no setup. Pick a repo/channel.
   For a docs site or blog, pick **Website (sitemap)** and paste its `sitemap.xml` URL.
4. **Sync now** — events flow ingest → classify → build, and the *Recent events*
   and *Context builds* panels light up.

The **Website (sitemap)** source crawls *every* page listed in a `sitemap.xml`
(it follows a sitemap index, handles gzip, reads `<lastmod>`, and re-crawls only
pages whose `<lastmod>` advanced). Crawling is deliberately polite so a connected
site is never overwhelmed — but completeness comes from rate-limiting, **not** from
dropping pages:

- The **Celery** crawler (`make crawler`, needs Redis) is the full-coverage path:
  it discovers all new/changed pages and fans out **one rate-limited task per
  URL**, so the whole site is covered at a bounded request rate.
- A dashboard **Sync** crawls inline as a quick connection test — bounded to
  `CRAWL_MAX_PAGES` per call (oldest-first), honouring `robots.txt`, with a
  concurrency cap and per-request delay.

The incremental cursor only advances past pages a poll *fully* crawled, so a
bounded poll resumes the rest next time instead of skipping the tail. Tune the
budget with the `CRAWL_*` vars in `.env.example`.

### Auth + Google sign-in setup

Set `JWT_SECRET` in `.env` to a long random string. For **Sign in with Google**,
register a Google Cloud OAuth client (Web application) with authorized redirect URI
`http://localhost:8000/auth/google/callback`, then set `GOOGLE_OAUTH_CLIENT_ID` /
`GOOGLE_OAUTH_CLIENT_SECRET`. Without them, the Google button is disabled and you use
email/password.

### Integration OAuth setup (for the Connect buttons)

Register your own apps and put the credentials in `.env`:

- **GitHub** → an OAuth App with callback `http://localhost:8000/oauth/github/callback`
  → set `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET`.
- **Slack** → an app with redirect `http://localhost:8000/oauth/slack/callback` and
  scopes `channels:history,channels:read` → set `SLACK_OAUTH_CLIENT_ID` /
  `SLACK_OAUTH_CLIENT_SECRET`.
- **Discord** → an app + bot with OAuth redirect `http://localhost:8000/oauth/discord/callback`,
  scope `bot` and bot permissions *View Channel* + *Read Message History* → set
  `DISCORD_OAUTH_CLIENT_ID` / `DISCORD_OAUTH_CLIENT_SECRET` / `DISCORD_BOT_TOKEN`. *Connect
  Discord* invites the bot into a server; the channel poller uses the bot token (enable the
  bot's **Message Content** privileged intent so it can read message text). Discord has no
  message webhook, so it is poll-only — *Sync* pulls a channel's recent messages.
- **LiveAgent** → no OAuth and nothing to set on the instance: each project pastes its own
  helpdesk **base URL** + a **v3 API key** (Configuration → System → API), then connects a
  *department* (optionally narrowed to a *tag*) as a source. The poller walks that department's
  tickets oldest-first by `date_changed`, folding each ticket's conversation into the event, and
  keeps a `"<date_changed>|<ticket_id>"` cursor so each *Sync* resumes where the last left off.

Without them, the *Connect* buttons are disabled and you use the manual path (a
public GitHub repo needs no token at all; LiveAgent always uses the per-project key).

### Smoke test (no network, no API key)

```bash
HARNEXT_HARNESS=fake make classifier      # in one shell
HARNEXT_HARNESS=fake make builder         # in another
uv run --package harnext-builder python scripts/smoke.py   # produce events
```

The 3 commits batch into one Context Unit; the P0 issue goes fast; the builder
incorporates both into `data/agentfs/.agentfs/acme.db`.

## Layout

| Path | What |
|------|------|
| `packages/shared` | CloudEvent envelope, ContextUnit, topics, DB models, session helpers |
| `apps/ingest` | source registry API + GitHub/Slack/Discord/LiveAgent/YouTube/Sitemap connectors (+ Celery crawler) → raw topic |
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
