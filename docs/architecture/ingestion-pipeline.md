# Ingestion Pipeline (v0)

> Status: **draft**, v0 scope.
> Owner: core team.
> Last updated: 2026-05-10.

## 1. Goal

Take any incoming signal — a document, a Jira ticket, a call transcript, a click, a webhook payload — and land it in Graphiti as a bitemporal episode, with **one normalization point** and **one extension point per new source**.

This is the spine of meaninggrid. Everything downstream — semantic search, agent surface, MCP server, dashboards — consumes the same normalized event stream. Getting this contract right early is more important than getting any single feature right.

## 2. Non-goals (v0)

These are deliberately deferred. They each get their own doc when we get there.

- **Classification / routing.** v0 ingests *everything*. There is no fast/batch lane split, no rules engine, no ML classifier, no LLM oracle. The pipeline has a single lane: source → Graphiti.
- **Search / vector index.** Graphiti is the only sink in v0. Qdrant, OpenSearch, etc. plug in later as additional Kafka consumers.
- **Frontend, agent surface, MCP server, auth, multi-tenancy.** Not in this doc.
- **Replay infrastructure** (Iceberg/Delta warehouse). Kafka retention is sufficient for v0.

## 3. Architecture

```
                                       ┌──────────────────┐
                                       │   MinIO (blobs)  │
                                       └────────▲─────────┘
                                                │ stores raw file
                                                │
 ┌────────┐   HTTP    ┌─────────┐   produce   ┌─┴──────────┐   consume   ┌──────┐   add_episode  ┌──────────┐
 │ Source │──────────▶│ Adapter │────────────▶│ Ingest API │────────────▶│Kafka │───────────────▶│ Worker  │──▶│ Graphiti │
 └────────┘  webhook  └─────────┘  envelope   └────────────┘ events.raw  └──┬───┘   bitemporal   └──────────┘   └──────────┘
              upload                                                       │ failure
                                                                           ▼
                                                                     events.dlq.v1
```

Eight moving parts:

| # | Component       | Responsibility                                                              | v0 implementation         |
|---|-----------------|-----------------------------------------------------------------------------|---------------------------|
| 1 | Source adapter  | Convert source-native input → CloudEvents envelope                          | `webhook`, `file`         |
| 2 | Ingest API      | Validate envelope, scope to tenant, stamp `ingest_time`, publish to Kafka   | FastAPI service           |
| 3 | OLTP store      | Tenant config, idempotency dedup, per-sink completion state, source credentials | SQLite via SQLAlchemy (Postgres-swappable) |
| 4 | Object storage  | Hold raw blobs (PDFs, audio, etc.); event references the URL                | MinIO                     |
| 5 | Kafka           | Durable, partitioned, replayable event log                                  | Redpanda or Apache Kafka  |
| 6 | DLQ             | Hold events that failed downstream processing                               | Topic `events.dlq.v1`     |
| 7 | Ingestion worker| Consume events, run processors and sinks                                    | Async Python (`aiokafka`) |
| 8 | Graphiti        | Bitemporal knowledge graph; the v0 sink (`group_id = mgtenant`)             | Graphiti with **FalkorDB** driver |

## 4. Event envelope

We use **[CloudEvents v1.0](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md)** as the universal envelope. Reasons:

- It's a real spec with SDKs in every language we'll touch.
- It collapses the N×M problem (N sources × M consumers) into N+M: every adapter emits CloudEvents, every consumer reads CloudEvents.
- It gives us first-class fields for the things we need (`source`, `type`, `subject`, `time`, `id`) plus a typed extension mechanism for the rest.

### Required attributes

| Field        | Meaning                                                     | Example                            |
|--------------|-------------------------------------------------------------|------------------------------------|
| `specversion`| CloudEvents version                                         | `"1.0"`                            |
| `id`         | Idempotency key, unique per event (see §8)                  | `"jira:ABC-42:rev-7"`              |
| `source`     | Logical source system                                       | `"jira"`, `"webhook:zendesk"`      |
| `type`       | Event type within the source                                | `"jira.issue.updated"`             |
| `subject`    | **Entity key.** Used as the Kafka partition key.            | `"ticket:ABC-42"`, `"user:42"`     |
| `time`       | `event_time` — when the thing happened in the source        | `"2026-05-10T12:34:56Z"`           |
| `datacontenttype` | MIME type of `data`                                    | `"application/json"`               |
| `data`       | Source-specific payload                                     | `{...}`                            |

### Meaninggrid extensions

| Field           | Meaning                                                          |
|-----------------|------------------------------------------------------------------|
| `mgingesttime`  | `ingest_time` — set by Ingest API, never trusted from caller     |
| `mgblobref`     | Object-store URL when payload is a blob (file uploads)           |
| `mgtenant`      | **Required.** Tenant id; set by Ingest API from auth context, never trusted from caller |

### Example: Jira ticket update

```json
{
  "specversion": "1.0",
  "id": "jira:ABC-42:rev-7",
  "source": "jira",
  "type": "jira.issue.updated",
  "subject": "ticket:ABC-42",
  "time": "2026-05-10T12:34:56Z",
  "datacontenttype": "application/json",
  "mgingesttime": "2026-05-10T12:34:57.012Z",
  "mgtenant": "acme",
  "data": {
    "issue_key": "ABC-42",
    "status": "In Review",
    "assignee": "alice@acme.com",
    "summary": "Fix the thing",
    "comment_added": "Looking at this now."
  }
}
```

### Example: PDF upload

```json
{
  "specversion": "1.0",
  "id": "file:9f8e7d6c5b4a",
  "source": "file",
  "type": "file.uploaded",
  "subject": "doc:9f8e7d6c5b4a",
  "time": "2026-05-10T12:00:00Z",
  "datacontenttype": "application/json",
  "mgingesttime": "2026-05-10T12:00:00.234Z",
  "mgblobref": "s3://meaninggrid-blobs/2026/05/10/9f8e7d6c5b4a.pdf",
  "data": {
    "filename": "Q2-strategy.pdf",
    "mime": "application/pdf",
    "size_bytes": 142318,
    "uploader": "yasha@meaninggrid.dev"
  }
}
```

## 5. Source adapters (v0)

### 5.1 Generic HTTP webhook

```
POST /ingest
Content-Type: application/json

{
  "source":  "webhook:zendesk",   // required
  "type":    "ticket.created",     // required
  "subject": "ticket:Z-1234",      // required, becomes Kafka partition key
  "time":    "2026-05-10T...",     // optional; if missing, server stamps now
  "id":      "...",                // optional; if missing, derived (see §8)
  "data":    { ... }               // arbitrary JSON payload
}
```

The adapter wraps the body in a CloudEvents envelope and hands off to the Ingest API. It does **not** inspect or transform `data`. Anyone can post anything that fits.

### 5.2 File / document upload

```
POST /ingest/file
Content-Type: multipart/form-data

file:    <binary>
source:  "file"   (or e.g. "drive:gdrive")
subject: "doc:..."
metadata: { "uploader": "...", "tags": [...] }   // optional JSON blob
```

The adapter:
1. Streams the file to MinIO.
2. Builds the envelope with `mgblobref` pointing at the MinIO object and `data` carrying metadata only.
3. Hands off to the Ingest API.

**Text extraction (PDF→text, audio→transcript, etc.) does not run in the adapter.** It runs in the worker (§7). Keeping it out of the request path means uploads return immediately and slow extractors don't block users.

### 5.3 Adapter contract

To add a new source — Slack, Jira native connector, Google Drive watch, Stripe webhook, anything — implement exactly this:

> **Receive whatever the source gives you. Produce a valid CloudEvents envelope. Publish via the Ingest API.**

That's it. Nothing else in the pipeline changes. This is the only extension point, by design.

## 6. Ingest API

A thin FastAPI service. Single responsibility: get events into Kafka safely.

Pseudocode:
```python
@app.post("/ingest", status_code=202)
def ingest(envelope: CloudEvent, auth: AuthContext = Depends(authenticate)):
    validate(envelope)                          # required fields + schema
    envelope.mgtenant = auth.tenant_id          # always derived from auth, never trust caller
    envelope.mgingesttime = utcnow()            # always server-set, never trust caller
    if envelope.id is None:
        envelope.id = derive_id(envelope)       # see §8
    producer.send(
        topic="events.raw.v1",
        key=f"{envelope.mgtenant}:{envelope.subject}".encode(),  # tenant-scoped, entity-keyed
        value=envelope.to_json(),
    )
    return {"id": envelope.id, "accepted_at": envelope.mgingesttime}
```

Notes:
- `mgtenant` and `mgingesttime` are **always** server-set from auth context and clock. Caller-supplied values are ignored. These are the tenant boundary and audit anchor.
- We return `202 Accepted`, not `200`. The event is durably in Kafka before we respond, but it has not yet been written to Graphiti.
- No business logic here. The Ingest API does not read `data`. It does not call Graphiti. It does not call the LLM. Keeping this boundary thin is what lets us scale and replace the downstream worker independently.
- The Ingest API reads tenant config from the OLTP store (§3 component 3) — at minimum to validate that the auth'd tenant is active and the source name is whitelisted.

## 7. Kafka topology

Two topics in v0:

### `events.raw.v1`
- The firehose. Every event from every tenant from every source.
- **Partition key**: `f"{mgtenant}:{subject}"` — tenant-scoped, entity-keyed. All events for the same entity within the same tenant land on the same partition → per-entity ordering preserved. This matters for Graphiti, where the order of episodes against the same entity changes the resulting graph. Tenants share a topic but never share a partition for the same `subject` value (avoids cross-tenant collisions on common keys like `customer:42`).
- Suggested config: 30 partitions, 7-day retention, `compression.type=zstd`.
- Schema: CloudEvents JSON (no schema registry in v0; we'll move to Avro/Protobuf when we have a second consumer).
- Tenant strategy: **shared topic, tenant in key + envelope.** Per-tenant topics are revisited only when one tenant's volume justifies its own partition allocation or its own retention SLA.

### `events.dlq.v1`
- Dead-letter for events the worker could not process after retries.
- Each DLQ message wraps the original event plus error metadata: `{ "original": {...}, "error": "...", "stage": "graphiti_write", "attempt": 3, "ts": "..." }`.
- Retention: 30 days. We expect humans (or a future remediation tool) to look at this.

### Why Kafka, not a simpler queue, in v0
1. **Replay.** When the worker logic changes (and it will), we replay from Kafka without touching the source.
2. **Fan-out.** As soon as we add a second sink (search index, analytics, audit log), they all read the same topic. No second pipeline.
3. **Backpressure isolation.** Graphiti writes can be slow (LLM-driven entity extraction). Kafka absorbs the spike so the Ingest API stays snappy.
4. **It's the spine of every later stage** in the thesis architecture (classification cascade, feedback loop, fast/batch lane). Putting it in now avoids a forklift upgrade later.

## 8. Idempotency & ordering

### Event id derivation

Order of preference:
1. **Source-provided id**, namespaced: `"{source}:{source_id}:{revision}"`. Example: `"jira:ABC-42:rev-7"`.
2. **Content hash**, when source can't supply a stable id: `"{source}:sha256({canonical_data})"`.
3. **UUID v7**, when neither is appropriate (rare; should be a last resort because it loses dedup ability).

### Dedup

The worker (not the Ingest API) tracks seen ids. Reasons:
- Letting Kafka accept duplicates is fine — they're cheap. The cost is a duplicate Graphiti episode, which we'd rather avoid.
- Dedup in the worker keeps the Ingest API stateless.
- Implementation: a `seen_events(tenant_id, event_id, processed_at)` table in the OLTP store with a composite primary key. Dedup is **per-tenant** — a Pipedrive event id from tenant A and the same id from tenant B are different events. TTL matches Kafka retention.

### Per-entity ordering

Guaranteed by Kafka partitioning on `f"{mgtenant}:{subject}"`. The worker's consumer uses a single thread per partition (or a key-aware executor) so events for the same entity within the same tenant are processed in publish order. Cross-tenant events for the same `subject` value land on different partitions and are independent.

## 8a. OLTP state — SQLite (v0)

Cross-cutting transactional state lives in a single OLTP store. v0: **SQLite** behind SQLAlchemy. Tables (initial set):

- `tenants(id, name, status, created_at)`
- `seen_events(tenant_id, event_id, processed_at)` — dedup
- `sink_outcomes(tenant_id, event_id, sink_name, status, attempts, last_error, completed_at)` — per-sink completion tracking, what `/api/v1/events/{id}` returns
- `connections(tenant_id, source, credentials_blob, scopes, refreshed_at)` — encrypted source credentials (Pipedrive OAuth, Zendesk keys, etc.)
- `tenant_config(tenant_id, key, value)` — per-tenant settings (allowed sources, AI prompts, label taxonomies)

Decision rationale (recorded so it's not re-litigated):
- **Why SQLite, not Postgres** for v0: zero ops, single binary, fastest path to a deployable product. Multi-tenant SaaS at small volume runs fine on SQLite (WAL mode).
- **Why not SQLite at scale**: single-writer engine. Once the worker fleet has multiple async processes hammering it, lock contention becomes real even with WAL. We treat SQLite as the v0 driver, not a permanent commitment.
- **Migration path**: SQLAlchemy with a dialect-agnostic schema. **No SQLite-specific features** (no FTS5, no JSON1-only quirks, no `WITHOUT ROWID`). Postgres swap is a connection-string change + Alembic apply, not a rewrite.

## 9. Ingestion worker — pipeline architecture

The worker is the busiest box in the diagram and the one most likely to grow new responsibilities. Today it does extraction + writes to Graphiti. Tomorrow it might compute a document-level vector embedding and write to Qdrant; build a keyword index for OpenSearch; run PII redaction; tee to a long-term audit log. We want each of those additions to be **one-file changes**, with no edits to Graphiti code, the Kafka topology, the envelope, or any other processor or sink.

The pattern: **two phases per event — Processors (sequential, middleware) then Sinks (parallel, independent).**

### 9.1 Why split into processors and sinks

The work breaks into two kinds of stages with different properties:

| Property              | Processors (Phase A)                     | Sinks (Phase B)                              |
|-----------------------|------------------------------------------|----------------------------------------------|
| Order                 | Matters (chunk before embed)             | Doesn't matter                               |
| State                 | Share an `IngestionContext`              | Read the final context; no shared writes     |
| Dependencies          | Declared (`requires` / `produces`)       | Declared (`requires`)                        |
| On failure            | Whole event → global DLQ                 | That sink → its per-sink DLQ; others proceed |
| Failure isolation     | None — chain is fragile by design        | Full — one bad backend can't stop the rest   |

Forcing both into one pattern means inheriting one trade-off for both. Splitting gives us composable enrichment **and** independent storage in the same worker.

```
       ┌──────────── PHASE A: PROCESSORS (sequential, middleware) ────────────┐   ┌─── PHASE B: SINKS (parallel) ───┐
event ─┤ extract_text  →  chunk  →  embed_doc  →  redact_pii  →  ...         │ ─→│ graphiti  qdrant  opensearch ... │
       └──────────────────────────────────────────────────────────────────────┘   └──────────────────────────────────┘
                              shared IngestionContext (immutable event + mutable artifacts)
```

### 9.2 IngestionContext

The single data carrier passed through both phases.

```python
@dataclass
class IngestionContext:
    event: CloudEvent          # immutable: the envelope as it came off Kafka
    artifacts: dict[str, Any]  # additive: what processors compute

    # Conventional artifact keys:
    # artifacts["text"]          — extracted full text (str)
    # artifacts["chunks"]        — list[str] of text chunks
    # artifacts["embedding"]     — np.ndarray for the whole document
    # artifacts["chunk_embeds"]  — list[np.ndarray] per chunk
    # artifacts["summary"]       — short LLM summary
```

Rules:
- `event` is **immutable**. If a processor needs to "rewrite" the event, it adds an artifact (e.g., `artifacts["normalized_payload"]`) instead. Sinks decide what they trust.
- `artifacts` is **additive**. Processors add keys; nobody removes or overwrites. Conflicts at registration time, not runtime.

### 9.3 Processor interface (the middleware pattern)

A processor is a middleware: it gets `(ctx, next)`, may mutate `ctx.artifacts`, calls `next` to continue the chain, and may short-circuit (rare).

```python
Middleware = Callable[
    [IngestionContext, Callable[[], Awaitable[IngestionContext]]],
    Awaitable[IngestionContext],
]

class Processor(Protocol):
    name: str
    requires: list[str]    # artifact keys this processor reads
    produces: list[str]    # artifact keys this processor writes

    async def __call__(self, ctx: IngestionContext, next_) -> IngestionContext: ...
```

Composition — the standard onion:

```python
def build_chain(processors: list[Processor]):
    async def run(ctx):
        async def step(i):
            if i == len(processors):
                return ctx
            return await processors[i](ctx, lambda: step(i + 1))
        return await step(0)
    return run
```

Example processor:

```python
class ExtractTextProcessor:
    name = "extract_text"
    requires = []
    produces = ["text"]

    async def __call__(self, ctx, next_):
        if ctx.event.mgblobref:                       # only for blob events
            ctx.artifacts["text"] = await self._extract(ctx.event.mgblobref)
        return await next_()
```

**Why middleware shape, not plain sequential calls?** Two things you can't get cleanly without it:

1. **Wrap-around work** — a processor can do work both *before* and *after* `next()`. This is how cross-cutting concerns (timing, tracing, retry, logging) compose: they're middlewares applied as decorators around real processors.
2. **Conditional short-circuit** — a processor can return without calling `next()` to drop an event (rare, but useful for "this is junk, don't bother").

Ordering is **declared, not positional**. At worker startup we topologically sort processors by `requires`/`produces`. Cycles or missing producers fail fast, before the first event.

### 9.4 Sink interface

A sink is a terminal handler that consumes the final context. It is **not** middleware. It does not call `next`. It does not chain.

```python
class Sink(Protocol):
    name: str
    requires: list[str]    # artifact keys this sink reads

    async def write(self, ctx: IngestionContext) -> None: ...
```

Sinks run **in parallel** at the end of Phase A. Each sink:

- Owns its **idempotency**, keyed on `ctx.event.id`. Prefer the sink's native upsert (Graphiti episodes by id, Qdrant points by id) over a side-table.
- Has its own **retry policy** (per-sink config: max attempts, backoff curve).
- Has its own **per-sink DLQ topic** (`events.dlq.graphiti.v1`, `events.dlq.qdrant.v1`, …). One per sink so we can replay a single sink's failures without re-running successful ones.
- Declares its `requires`. The worker validates at startup that processors produce them.

Example sink:

```python
class GraphitiSink:
    name = "graphiti"
    requires = []   # consumes event.data directly; or "text" if a processor extracted it

    async def write(self, ctx):
        body = ctx.artifacts.get("text") or json.dumps(ctx.event.data)
        await self.client.add_episode(
            name=f"{ctx.event.source}:{ctx.event.type}:{ctx.event.id}",
            episode_body=body,
            reference_time=ctx.event.time,
            source_description=ctx.event.source,
        )
```

### 9.5 Worker loop

```python
async def handle(event: CloudEvent):
    if dedup.seen(event.id):
        return

    ctx = IngestionContext(event=event, artifacts={})

    try:
        ctx = await processor_chain(ctx)               # Phase A: sequential
    except Exception as exc:
        await global_dlq.publish(event, exc, stage="processor")
        return                                          # don't run sinks on a broken chain

    results = await asyncio.gather(                    # Phase B: parallel
        *[run_sink_with_retries(sink, ctx) for sink in sinks],
        return_exceptions=True,
    )
    for sink, result in zip(sinks, results):
        if isinstance(result, Exception):
            await per_sink_dlq[sink.name].publish(event, result)

    dedup.mark(event.id)
```

Concurrency: one Kafka consumer group, multiple worker processes; Kafka assigns partitions. Per-partition single-flight (one in-flight event at a time per partition) preserves entity ordering for Phase A. Phase B parallelism is *within* a single event across sinks, not across events on the same partition.

#### Runtime choice — why not Celery

The worker is **`aiokafka` + `asyncio`**, not Celery. Decision rationale, recorded so it doesn't get re-litigated:

- **Kafka is already the queue.** Adding Celery means running two brokers (Kafka + Redis/RabbitMQ) and two concurrency models on top of each other. Pure operational tax with nothing gained that Kafka consumer groups don't already give us.
- **Per-entity ordering would be lost.** Once an event leaves the Kafka consumer for a Celery task, partition ordering is gone (Celery routes by queue, not by key within a queue). Restoring it requires custom routing per `subject`, which is a significant chunk of bespoke code — and Graphiti's temporal graph quality depends on that ordering.
- **Two-phase commit on offsets.** Committing the Kafka offset before Celery confirms risks event loss; committing after blocks the consumer on Celery's pace. Either way, Celery becomes the bottleneck, not the helper.
- **What Celery is good for, we don't need.** Beat scheduling — no. Complex DAGs (chord/group/chain) — no, our pipeline is linear processors + flat sink fan-out. Web-app background tasks — n/a, we have a stream.

Where we'd revisit: if a future team has deep Celery muscle memory and shallow Kafka muscle memory, or if Kafka becomes only an integration boundary and the primary unit of work shifts to web-request-triggered tasks. Neither is true today.

### 9.6 Failure semantics

| What failed       | What happens                                                                           |
|-------------------|----------------------------------------------------------------------------------------|
| A processor       | Whole event → `events.dlq.v1`. No sinks invoked. Dedup **not** marked → safe to replay.|
| One sink          | That sink → its per-sink DLQ. Other sinks succeed. Dedup marked.                       |
| All sinks         | Each sink → its own per-sink DLQ. Dedup marked.                                        |

The principle worth being deliberate about: **partial-success sinks are normal**. Cost: you must monitor each per-sink DLQ. Benefit: one bad backend can't take the system down.

Replay strategy: **per-sink DLQ topics are themselves Kafka topics** that can be consumed by a small "DLQ replayer" tool. To re-run only Qdrant after fixing a bug, drain `events.dlq.qdrant.v1` through the QdrantSink alone. Graphiti is untouched.

**Retry mechanics — the retry-topic pattern.** "Exponential backoff with N attempts" is implemented Kafka-natively, not in-process: on transient failure, a sink republishes the event to a delayed retry topic (e.g., `events.retry.qdrant.5s.v1`, `events.retry.qdrant.30s.v1`, …) which feeds back into the sink after the delay elapses. After the final retry topic, failures land in the per-sink DLQ. This keeps the main consumer loop unblocked, makes retries observable (you can see depth and lag per delay tier), and avoids in-memory retry state that vanishes on worker restart. This is the standard Uber/Confluent retry pattern; we don't need to invent anything.

### 9.7 Adding a new processor

1. Implement the `Processor` protocol in `apps/worker/processors/{name}.py`.
2. Declare `requires` and `produces` honestly. The topological sort depends on it.
3. Register in worker config. Done.

### 9.8 Adding a new sink

1. Implement the `Sink` protocol in `apps/worker/sinks/{name}.py`.
2. Declare `requires`. Make `write` idempotent on `ctx.event.id` (prefer the backend's native upsert).
3. Register the sink + its per-sink DLQ topic in worker config.
4. Done. No edits to processors, other sinks, Graphiti code, the envelope, or Kafka.

If implementing a new sink requires touching anything outside its own file + config, **the design is being violated**. Push back.

### 9.9 Worked example — adding a vector sink (post-v0)

Scenario: we want a single embedding for the whole document, stored in Qdrant alongside the Graphiti write.

**Changes:**
1. New processor `embed_document` — `requires=["text"]`, `produces=["embedding"]`. Calls embedding API; stores `np.ndarray` in `artifacts["embedding"]`.
2. New sink `qdrant` — `requires=["embedding"]`. `write()` upserts a point with `id=ctx.event.id`, `vector=ctx.artifacts["embedding"]`, payload `{source, type, subject, time}`.
3. Config registration for both.

**What does NOT change:** Ingest API. Adapters. Kafka topology. CloudEvents envelope. GraphitiSink. Dedup. ExtractTextProcessor. Worker loop.

This is the design's success metric.

### 9.10 Future: when a sink should leave the worker

Today every sink runs in-process inside the worker. That's correct for v0 and probably for the next several sinks. When a sink should be split out into its own Kafka consumer group (own deployment, own scaling, own failure domain):

- It's CPU-heavy enough to starve other sinks (e.g., embedding model on GPU).
- It belongs to a different team or release cadence.
- It needs different scaling characteristics (much more or fewer instances).

The Sink contract is intentionally compatible with both: an in-process sink and an out-of-process consumer of `events.raw.v1` look the same to the rest of the system. We move sinks out when there's a real reason, not preemptively.

## 10. Graphiti integration

Graphiti is the **v0 implementation of the Sink interface** (§9.4). The mapping below is what `GraphitiSink.write()` does. Future sinks (Qdrant, OpenSearch, audit log) follow the same Sink contract; the choice of "which sinks ship in v0" is a config decision, not an architectural one.

Each event becomes exactly one Graphiti **episode**. Mapping:

| Graphiti field    | Source                                             |
|-------------------|----------------------------------------------------|
| `name`            | `f"{event.source}:{event.type}:{event.id}"`        |
| `episode_body`    | extracted text (file) or `json.dumps(event.data)`  |
| `source_description` | `event.source`                                  |
| `reference_time`  | `event.time` (the `event_time`)                    |
| `source`          | `EpisodeType.text` or `EpisodeType.json`           |
| `group_id`        | `event.mgtenant` — Graphiti's tenant boundary; queries scope to `group_id` |

### The bitemporal invariant

Every Graphiti write carries **two timestamps**:

- **`event_time`** — `event.time` from the CloudEvents envelope. When the thing happened in the world.
- **`ingest_time`** — `event.mgingesttime`. When meaninggrid observed it.

`reference_time` on the episode captures `event_time`. Graphiti's own `created_at` on the resulting nodes/edges captures the wall-clock at write, which is effectively `ingest_time` (within milliseconds — close enough for v0).

This is non-negotiable. It's what makes "what did we believe about customer X on April 1?" answerable. Backfilling bitemporality after the fact requires re-deriving the graph from raw events, which is expensive and error-prone — so we pay the small cost of doing it correctly from day one.

### What we don't do in v0

We don't pre-extract entities or relationships before handing to Graphiti. Graphiti runs its own LLM extraction over `episode_body`. Our job is to deliver the right episode at the right time with the right timestamps; let Graphiti do graph-building.

## 11. Adding a new source (recipe)

The whole architecture exists to make this list short:

1. **Write an adapter** that consumes the source's native format (webhook payload, polled API, change feed) and emits a CloudEvents envelope. Place it under `apps/ingest/adapters/{source_name}/`.
2. **Register the source name** in the adapter registry so logs and metrics tag it correctly.
3. **Deploy.** Adapter publishes to the existing `/ingest` endpoint or directly to the Ingest API's producer. Nothing else changes — not the topic, not the worker, not Graphiti.

If implementing this requires touching the worker, the Kafka topic, or Graphiti code, **the design is being violated**. Push back.

## 12. Observability

Each component emits at minimum:

- **Adapter / Ingest API**: events accepted per source/type, validation errors, p50/p95/p99 latency.
- **Kafka**: consumer lag per partition, producer error rate, DLQ size and growth.
- **Worker**: events processed per source/type, extraction time, Graphiti write latency, retry counts.
- **Graphiti**: write success rate, episode count, graph node/edge growth.

Concrete library choices (OTel, Prometheus, etc.) are deferred to the operations doc. Whatever we pick, the *what* above is the floor.

## 13. Future stages (deliberately deferred)

Each of these is a design decision already made (in the thesis), and a doc to be written when we get there. Listed so reviewers don't ask "but where's X?".

- **AI / analysis layer.** Sentiment, summary, theme detection, label assignment, churn-risk scoring, operator-quality scoring, script-compliance check, next-step recommendations. **These will be Processors** in the §9.3 sense — the design choice is already made, the implementation is the next phase. Each AI task is one processor; together they enrich the `IngestionContext` with artifacts that downstream sinks (Graphiti, Postgres for reporting, etc.) can consume. Listed first because it's the next thing being built.
- **Real-time path** for live-call features (competitor battlecards). Short-circuits the full pipeline; streaming STT → keyword/competitor matcher → WebSocket to operator UI. Will not reuse the Kafka spine for the live latency budget. Deferred to v1.
- **CRM write-back** (egress to Pipedrive et al.). Mirror of the ingestion direction; needs its own retry / conflict / rate-limit story. Its own doc.
- **Classification cascade** (envelope rules → declarative rules → small classifier → LLM oracle). Drops in between the worker's consume and Graphiti write, or as a separate consumer producing routing decisions to a dedicated topic.
- **Fast/batch lane split.** Today: one topic, everything goes to Graphiti. Future: `events.fast.v1` + `events.batch.v1` for urgent vs aggregated paths.
- **Feedback loop.** `routing_feedback.v1` topic; agents emit verdicts; feeds bandit + classifier retraining.
- **Replay-from-warehouse.** Iceberg/Delta sink alongside Kafka so we can replay from cold storage when Kafka retention runs out or aggregation logic changes (Kappa+).
- **Additional sinks.** Qdrant for vectors, Postgres for analytics/reporting, audit log. Each is a new Sink (§9.4) plus, when needed, a new Processor (§9.3) that produces what the sink consumes. See §9.9 for the Qdrant walkthrough. Sinks that outgrow the worker (heavy CPU, separate scaling, separate team) get split into their own Kafka consumer groups (§9.10).
- **Postgres swap-out** for OLTP store when SQLite write-contention becomes real. Schema is dialect-agnostic from day one (§8a).
- **Schema registry.** Move from JSON to Avro/Protobuf with a registry once we have ≥2 consumers and breaking-change risk is real.

## 14. Open questions

Not yet decided; flagging so they don't get smuggled in by default:

- **PII redaction**: adapter (early, before Kafka) or worker (late, before Graphiti)? Trade-off is "nothing sensitive ever hits Kafka" vs "redaction logic lives in one place not N adapters". Likely a Processor in §9.3 once the AI layer lands.
- **Source authentication & credential storage**: how Pipedrive OAuth, Zendesk API keys, IMAP creds are scoped per tenant, refreshed, and rotated. Probably a `connections` service backed by the OLTP store (§8a) with per-tenant encryption keys. Needs its own doc.
- **Right-to-be-forgotten (GDPR)**: deleting a merchant from the graph. Graphiti's bitemporal model + cascades is non-trivial. Open.
- **Retry budget**: how many times does the worker retry before DLQ? What's the backoff curve?
- **Blob lifecycle**: when does MinIO garbage-collect blobs whose events have been ingested? Tied to whether we ever need to re-extract.
- **Audio-specific pipeline** (call recordings): STT provider, diarization, multi-language, separate retention for audio vs transcript. Likely its own `sources/calls.md` doc.

## References

- CloudEvents v1.0 spec: <https://github.com/cloudevents/spec>
- Graphiti: <https://github.com/getzep/graphiti>
- Master's thesis (architectural source-of-truth): `~/Desktop/uni/masters/masters-streaming-ai-agent-architecture/` — see `proposal.md`, `report.md`, `research/RQ5-shared-memory.md`.
