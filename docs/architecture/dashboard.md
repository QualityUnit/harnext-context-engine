# Dashboard (v0)

> Status: **draft**, v0 scope.
> Owner: core team.
> Last updated: 2026-05-10.

## 1. Goal

A web dashboard that lets a user (a) see what's been ingested, (b) explore the knowledge graph Graphiti has built, and (c) search across entities and facts. The graph view is the centerpiece — for meaninggrid, *the visualization is the product surface*.

We are **not** embedding a third-party graph viz tool (FalkorDB Browser, Neo4j Browser/Bloom, etc.). They have no embeddable React SDK, and even if they did, they show **raw graph-DB rows**, not the **semantic graph** Graphiti has built. Different abstraction level, different audience. We build the graph view ourselves, taking architectural inspiration from FalkorDB Browser's Next.js codebase but tailoring everything to entities, facts, and episodes — meaninggrid's domain.

## 2. Non-goals (v0)

- Real-time updates as new events ingest. v0 polls / revalidates on user action.
- Graph **editing** (add/delete/relabel nodes from the UI). View-only in v0; the graph is built by ingestion.
- Natural-language → Cypher chat. Future.
- Saved views, alerts, dashboards-of-dashboards. Future.
- Tenant administration UI (creating tenants, managing per-tenant config). v0 ships with multi-tenant **primitives** — every API call is tenant-scoped — but tenants are seeded via the OLTP store (`ingestion-pipeline.md` §8a), not through the dashboard.
- Production auth flows (SSO, MFA). v0 uses a simple session-based auth tied to operator accounts in the OLTP store; full identity story gets its own doc.

## 3. Architecture

```
┌────────────┐  HTTP/JSON   ┌──────────────┐    Python   ┌──────────┐    Cypher    ┌─────────────────┐
│  Next.js   │─────────────▶│  Backend API │────────────▶│ Graphiti │─────────────▶│    FalkorDB     │
│  (React +  │   /api/v1/.. │   (FastAPI)  │ graphiti_   │          │              │ (Redis-based)   │
│ Cytoscape) │              │              │  _core      └──────────┘              └─────────────────┘
└────────────┘              └──────────────┘
```

Three layers, one rule: **the frontend never talks to the graph DB directly.** Consequences:

- Auth, query sanitization, tenant scoping all live in the backend.
- Switching the graph DB later (FalkorDB ↔ Neo4j) is a backend change. The dashboard doesn't notice.
- We expose a clean meaninggrid API (entities, facts, episodes, time slices), not Cypher.

**Multi-tenancy is a v0 invariant.** Every backend request derives `tenant_id` from the auth context and scopes every Graphiti query (via `group_id`) and every OLTP query (via `tenant_id` column). The frontend never sets the tenant; it asks for "my data" and the backend resolves what that means. This matches the ingestion-side decision (`ingestion-pipeline.md` §6, §8a).

**Graph DB choice: FalkorDB.** Rationale:
- Redis-based, single container in docker-compose — no JVM, lighter local-dev footprint than Neo4j.
- Same Graphiti API; we'd write the same `add_episode` / `search` calls regardless. Driver swap is a config change.
- The wire shape (§6) is still DB-agnostic — switching to Neo4j later remains a backend-only change.

Because we use FalkorDB, the FalkorDB Browser source code (§5) is even more directly applicable as a reference: same Cypher dialect, same client library, same data model.

## 4. Frontend stack

| Concern        | Choice                                                                  | Why |
|----------------|-------------------------------------------------------------------------|-----|
| App framework  | **Next.js 15+** (App Router)                                            | SSR for shell, client-side for canvas, file routing. Same choice as FalkorDB Browser; no surprises. |
| Graph viz      | **Cytoscape.js** + **`react-cytoscapejs`** + **`cytoscape-fcose`**      | Most mature open-source graph library. fcose handles clustered subgraphs well. Comfortably renders thousands of nodes. |
| UI primitives  | **Radix UI** + **Tailwind CSS**                                         | Headless components + utility CSS. Composable, no design-system lock-in. |
| Data fetching  | **SWR**                                                                  | Cache + revalidation + stale-while-revalidate. Right size for our endpoints. |
| Forms          | **react-hook-form**                                                      | Standard. |
| Code editor    | **Monaco** (deferred to future query playground)                         | If/when we add a Cypher / DSL playground. |

We considered **`@neo4j-nvl/react`** (Neo4j's first-party React graph viz). Rejected: picking it would have locked us to Neo4j, and we picked FalkorDB (§3).

## 5. What to take from FalkorDB Browser — and what not to

We are reading [`FalkorDB/falkordb-browser`](https://github.com/FalkorDB/falkordb-browser) (Next.js 16, Cytoscape, Radix, Tailwind, SWR) as a reference codebase, not a dependency.

### Borrow

- **The stack itself** — Cytoscape + Next.js + Radix + Tailwind + SWR. Validated combination; no need to second-guess.
- **fcose layout as the default.** Compound force-directed; clusters look like clusters. Their default for the same reason it should be ours.
- **Three views over the same data** (`GraphView`, `TableView`, `MetadataView`). Graph for spatial intuition, table for filtering at scale, metadata for inspection. We adopt this verbatim.
- **Panel-driven layout.** Separate panels for selection details, history, customization. Keeps the canvas clean. They have ~9 panels in `app/graph/`; we'll have fewer to start.
- **SWR over fetch hooks.** Cache and revalidation come for free; their data flow leans on it.

### Don't borrow

- **Their level of abstraction.** FalkorDB Browser shows arbitrary graph-DB nodes and edges — any label, any property. Our domain is **entities, facts, episodes, communities**. Frontend types and components should be named for *that* domain, not generic `Node`/`Edge`. This is the single biggest divergence.
- **Chat-to-Cypher tab.** They ship `@falkordb/text-to-cypher` for NL → query. Skipping in v0; it leaks the underlying DB abstraction (we don't want users writing Cypher against meaninggrid).
- **Graph editing controls** (`CreateElementPanel`, `addLabel`, `RemoveLabel`, `DeleteElement`). Our graph is **built by Graphiti from ingestion**. Manual edits aren't in the model.
- **`next-auth` for DB credentials.** Their auth boundary is "user → DB". Ours is "user → backend"; the backend is the one with DB credentials. The frontend is unauthenticated against the graph DB by construction (§3).
- **Their Cypher editor.** v0 has no raw query surface.

## 6. Backend API contract (v0)

The minimum surface the dashboard needs. All under `/api/v1/`. JSON in, JSON out.

| Endpoint                          | Returns                                                                |
|-----------------------------------|------------------------------------------------------------------------|
| `GET /events`                     | Paginated list of recent ingested events                               |
| `GET /events/{id}`                | Full event envelope + per-sink processing status (Graphiti written? Qdrant? DLQ?) |
| `GET /graph`                      | Subgraph as `{nodes, edges}` for the viz (the workhorse)               |
| `GET /entities/{uuid}`            | Entity details + one-hop neighborhood                                  |
| `GET /entities/search?q=...`      | Hybrid search across entities. Wraps `Graphiti.search_()`.             |
| `GET /facts/search?q=...`         | Hybrid search across edge facts. Wraps `Graphiti.search()`.            |
| `POST /ingest` (proxy)            | Forwarded to the ingest-api (see ingestion-pipeline.md §6)             |

`GET /graph` is the workhorse. Query params:

- `subject` — entity uuid to center on (or omitted for top-level)
- `depth` — 1–3 hops
- `since` / `until` — bitemporal slicing (the dashboard's time slider)
- `limit` — max nodes returned

Wire shape:

```json
{
  "nodes": [
    {
      "id": "uuid-1",
      "kind": "entity",
      "name": "Acme Corp",
      "summary": "Customer since 2024",
      "labels": ["Organization", "Customer"],
      "valid_at": "2024-03-01T...",
      "invalid_at": null
    }
  ],
  "edges": [
    {
      "id": "uuid-2",
      "source": "uuid-1",
      "target": "uuid-3",
      "fact": "Acme Corp raised ticket ABC-42",
      "valid_at": "2026-04-15T...",
      "invalid_at": null,
      "episode_uuid": "uuid-9"
    }
  ]
}
```

This is graph-DB-agnostic and Cytoscape consumes it directly with a small `{data: {...}}` wrap.

## 7. Graph view module

Mirrored from FalkorDB Browser's `app/graph/` decomposition, adapted to our domain:

```
apps/web/app/graph/
  page.tsx              — entry; SWR-driven data fetching
  GraphView.tsx         — Cytoscape canvas
  TableView.tsx         — same nodes/edges as a sortable table
  EntityPanel.tsx       — sidebar for selected entity (their DataPanel + MetadataView, unified)
  Toolbar.tsx           — layout switcher, depth slider, time slider
  StylePanel.tsx        — node/edge style customization (placeholder in v0)
  layouts.ts            — fcose preset + alternatives (cose-bilkent, dagre)
  styles.ts             — Cytoscape stylesheet (entity-type colors, edge thickness by recency)
  types.ts              — frontend types: Entity, Fact, Episode, Community
```

The **bitemporal time slider** is the meaninggrid-specific addition: a slider on the toolbar that controls `since` / `until`, so the user can ask "what did the graph look like on 2026-04-01?". This is the visible payoff of the §10 bitemporal invariant from `ingestion-pipeline.md` — we built it; we should surface it.

## 8. Embeddings — what Graphiti gives us, what we'd add

Worth being explicit because the answer is non-obvious.

**What Graphiti embeds (and where the vectors live):**

| Object         | Field             | What's embedded                                               |
|----------------|-------------------|---------------------------------------------------------------|
| `EntityNode`   | `name_embedding`  | The entity's name (e.g., `"Acme Corp"`)                       |
| `CommunityNode`| `name_embedding`  | The community label                                            |
| `EntityEdge`   | `fact_embedding`  | The relationship fact (e.g., `"Acme Corp raised ticket ABC-42"`) |
| `EpisodicNode` | (none)            | **Episodes are NOT embedded by Graphiti.**                     |
| `EpisodicEdge` | (none)            | Not embedded.                                                  |

So Graphiti's vector search operates over **extracted entities and facts**, not raw episode bodies. This is by design — Graphiti's job is to build the semantic graph, not to be a document store.

**How to access:**

- **Python API** (preferred):
  ```python
  await entity_node.load_name_embedding(driver)   # returns list[float]
  await entity_edge.load_fact_embedding(driver)
  ```
- **Direct Cypher** (escape hatch): `MATCH (n:Entity {uuid: $uuid}) RETURN n.name_embedding`. Provider-specific minor variations.
- **Graphiti search** (`Graphiti.search()` and `search_()`) uses these embeddings under the hood for hybrid (vector + BM25 + graph traversal) retrieval. Returns nodes/edges, not raw vectors. This is what `/api/v1/entities/search` and `/api/v1/facts/search` wrap.
- **No turn-key REST endpoint specifically for raw embeddings.** We expose what we need via our own backend.

**What this means for v0 dashboard search:**

| Query                                           | Available v0?               |
|-------------------------------------------------|-----------------------------|
| "Find entities mentioning *X*"                  | **Yes** — `Graphiti.search()` |
| "Find facts about *X*"                          | **Yes** — `Graphiti.search()` |
| "Find documents about pricing strategy"         | **No** — episodes aren't embedded |

For document-level semantic search, we'd add a `embed_document` processor and a vector-store sink (Qdrant / pgvector) — exactly the worked example in `ingestion-pipeline.md` §9.9. The pipeline is designed to make this additive (one new processor + one new sink, no other edits).

**Recommendation:** don't add document-level embeddings in v0. Entity/fact search via Graphiti is enough to ship a useful dashboard. Wait for a real query that requires document search before paying the embedding-storage tax.

## 9. Future

- **Live updates**: WebSocket / SSE channel from the worker to the dashboard so newly ingested entities appear without refresh.
- **Communities view**: visualize `CommunityNode`s as cluster boundaries on the canvas.
- **Document-level semantic search** (§8 + ingestion-pipeline.md §9.9).
- **NL query interface**: meaninggrid-flavored, constrained to entity/fact patterns (not raw Cypher).
- **Saved views**: bookmark a subgraph + time slice + filter set.
- **Tenant administration UI** (multi-tenant primitives are in v0; the *UI* for managing them is later) and full SSO / RBAC.

## 10. Open questions

- **Layout caching**: force-directed layouts are non-deterministic; positions jump on each load. Cache per-graph in localStorage, or recompute every time and let the user accept the wobble?
- **Dense subgraphs**: a popular entity may have 1000+ neighbors at depth 1. Cap, paginate, or auto-cluster?
- **Edge density on the same pair**: Graphiti emits multiple `EntityEdge`s for the same `(source, target)` over time (each fact is its own edge). Collapse them in the view, or surface a per-pair timeline panel?
- **Mobile**: Cytoscape supports touch but we haven't tested. Defer.

## References

- FalkorDB Browser source (the inspiration, not a dependency): <https://github.com/FalkorDB/falkordb-browser>
- Cytoscape.js: <https://js.cytoscape.org>
- `cytoscape-fcose` layout: <https://github.com/iVis-at-Bilkent/cytoscape.js-fcose>
- Graphiti core (embedding fields are in `graphiti_core/nodes.py` and `graphiti_core/edges.py`): <https://github.com/getzep/graphiti>
