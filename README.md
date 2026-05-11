# meaninggrid

> Turn heterogeneous business signals — calls, emails, CRM events, documents, clicks — into a queryable, bitemporal knowledge graph.

An open-source semantic intelligence platform. Ingest events from any source, let Graphiti extract entities and facts via LLM, query the resulting graph from a Next.js dashboard.

**Status:** v0 — end-to-end ingestion → graph works locally. See [`docs/architecture/`](./docs/architecture/) for the source-of-truth design and [Roadmap](#roadmap) for what's next.

---

## Architecture at a glance

```
                                       ┌──────────────────┐
                                       │   MinIO (blobs)  │
                                       └────────▲─────────┘
                                                │
 ┌────────┐   HTTP    ┌─────────┐   produce   ┌─┴──────────┐   consume   ┌──────────┐   add_episode  ┌──────────┐
 │ Source │──────────▶│ Adapter │────────────▶│ Ingest API │────────────▶│  Worker  │───────────────▶│ Graphiti │
 └────────┘  webhook  └─────────┘  CloudEvent └────────────┘ events.raw  └──────────┘   bitemporal   └─────┬────┘
              upload                                                                                       │
                                                                                                           ▼
                                                                                                     ┌──────────┐
                                                                                                     │ FalkorDB │
                                                                                                     └──────────┘
```

| Layer        | Tech                                                        |
|--------------|-------------------------------------------------------------|
| Frontend     | Next.js 15 (App Router) · React 19 · Cytoscape.js · Tailwind 4 · SWR |
| Backend API  | FastAPI · `aiokafka` · SQLAlchemy 2 async · `aioboto3`      |
| Worker       | Async Python · `aiokafka` consumer · `pypdf` extraction     |
| Knowledge graph | [Graphiti](https://github.com/getzep/graphiti) with the FalkorDB driver |
| LLM + embedder | Local [Ollama](https://ollama.com) (OpenAI-compatible API) |
| Streaming   | Redpanda (Kafka-compatible)                                  |
| Blob storage | MinIO (S3-compatible)                                       |
| OLTP store  | SQLite via `aiosqlite` (Postgres-swappable)                 |

The pipeline is multi-tenant by construction (every Kafka key, Graphiti `group_id`, and OLTP row carries `tenant_id`) and bitemporal (every write carries both `event_time` and `ingest_time`). Worker is structured as **Processors (sequential middleware) → Sinks (parallel)** so adding a new enrichment or a new sink is a one-file change.

## What works today

- **Ingest API** — `POST /api/v1/ingest` (JSON), `POST /api/v1/ingest/file` (multipart, PDFs + text)
- **Read API** — `GET /api/v1/events`, `GET /api/v1/events/{id}`, `GET /api/v1/graph`, `GET /api/v1/entities/search`
- **Worker** — consumes `events.raw.v1`, runs `ExtractTextProcessor` (PDFs/text), writes Graphiti episodes, records per-sink outcomes, ships failures to a global DLQ
- **Dashboard** — events list (auto-refreshing), event detail with sink status, **Cytoscape graph view** with fcose layout, ingest form (JSON event + file upload)
- **Local stack** — single `docker compose up` brings Redpanda + FalkorDB + MinIO

## Quickstart

Prerequisites: [`uv`](https://docs.astral.sh/uv/), [`pnpm`](https://pnpm.io), Docker, and a running [Ollama](https://ollama.com).

```bash
git clone git@github.com:yasha-dev1/meaninggrid.git
cd meaninggrid
cp .env.example .env

# Pull a small LLM + embedder for Graphiti (~2.3GB total)
ollama pull qwen2.5:3b
ollama pull nomic-embed-text

# Bring up infra and install deps
make up                    # Redpanda + FalkorDB + MinIO (wait until `make ps` shows healthy)
make install               # uv sync --all-packages + pnpm install
make bootstrap             # SQLite tables, MinIO bucket, seed 'default' tenant
```

Then in three terminals:

```bash
make api       # Ingest + read API on :8000     → http://localhost:8000/docs
make worker    # Ingestion worker (consumes Kafka, writes to Graphiti)
make web       # Next.js dashboard on :3100     → http://localhost:3100
```

`make help` lists every target.

## Try it

Open <http://localhost:3100/ingest> and post a JSON event (or upload a PDF). Or from the shell:

```bash
make smoke
```

Watch the event flow:
1. **`/events`** — new row appears within ~5s (auto-refreshes)
2. **Worker log** — `sink=graphiti event=… ok` when Graphiti finishes entity extraction (5–60s; first call loads the model)
3. **`/events/{id}`** — graphiti sink status flips to `success`
4. **`/graph`** — entities/edges Graphiti extracted appear on the Cytoscape canvas

Auth in v0 is just the `X-Tenant-Id` header. The dashboard sends `default` (the seeded tenant); change it via browser localStorage `meaninggrid.tenant` if you set up more tenants.

## Project layout

```
meaninggrid/
├── apps/
│   ├── api/        FastAPI service: ingest + read endpoints
│   ├── worker/     async Python: Kafka consumer + processor chain + sinks
│   └── web/        Next.js 15 dashboard
├── packages/
│   └── shared/     CloudEvent envelope, Processor/Sink protocols, OLTP models
├── infra/
│   └── docker-compose.yml      Redpanda + FalkorDB + MinIO
├── docs/
│   └── architecture/           ingestion-pipeline.md, dashboard.md
├── data/           SQLite + local state (gitignored)
├── pyproject.toml  uv workspace root
└── pnpm-workspace.yaml
```

## Configuration

All env vars live in `.env` (copy from `.env.example`). Key ones:

| Var                       | Default                                | Notes                                    |
|---------------------------|----------------------------------------|------------------------------------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092`                       | Redpanda Kafka API                       |
| `FALKORDB_HOST` / `PORT`  | `localhost` / `6380`                   | Mapped to 6380 to avoid local Redis      |
| `MINIO_ENDPOINT`          | `http://localhost:9000`                | Blobs                                    |
| `LLM_BASE_URL`            | `http://localhost:11434/v1`            | Ollama's OpenAI-compatible endpoint      |
| `LLM_MODEL`               | `qwen2.5:3b`                           | Anything Ollama serves. Bigger = better extraction, more memory. |
| `EMBEDDING_MODEL`         | `nomic-embed-text` (768d)              | Override `EMBEDDING_DIM` if you change it |
| `DATABASE_URL`            | `sqlite+aiosqlite:///./data/...`       | Postgres-swappable                       |

## Roadmap

Each is documented as a planned extension in `docs/architecture/`:

- **AI processors** — sentiment, summary, themes, label assignment, churn risk, operator quality, script compliance. Each is a single `Processor` per [§9.7](./docs/architecture/ingestion-pipeline.md).
- **Additional sinks** — Qdrant for vectors, Postgres for analytics, audit log. Each is a single `Sink` per [§9.8](./docs/architecture/ingestion-pipeline.md).
- **CRM write-back** — egress sibling of ingestion (Pipedrive, Zendesk, etc.).
- **Real-time path** — streaming transcription + competitor battlecards on live calls.
- **Source adapters** — Pipedrive, Zendesk, email, Twilio. Each plugs into the existing `/ingest` endpoint via the universal CloudEvents envelope.
- **Per-sink retry topics** — `events.retry.{sink}.{delay}.v1` for graceful exponential backoff.
- **Real auth** — SSO/JWT replacing the `X-Tenant-Id` header.

## Architecture docs

Read these in order:

1. [`docs/architecture/ingestion-pipeline.md`](./docs/architecture/ingestion-pipeline.md) — how events flow from any source into Graphiti. Covers the envelope, Kafka topology, worker pipeline (processors + sinks), failure semantics, multi-tenancy, the SQLite OLTP rationale.
2. [`docs/architecture/dashboard.md`](./docs/architecture/dashboard.md) — frontend architecture, what we borrow vs. adapt from FalkorDB Browser, the wire shape for `/graph`, embedding access strategy.

## License

[MIT](./LICENSE)
