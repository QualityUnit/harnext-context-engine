# meaninggrid-mcp

FastMCP server that lets an AI agent query the tenant's FalkorDB graph via
read-only Cypher and a few schema-introspection helpers.

## What it exposes

| Tool | Purpose |
| --- | --- |
| `read_cypher(query, params?)` | Run an arbitrary read-only Cypher query against the tenant's graph. Mutations (CREATE/MERGE/SET/DELETE/REMOVE/DROP/CALL …) are rejected before they hit the driver. |
| `list_labels()` | Distinct node labels present in the graph (e.g. `Entity`, `Episodic`). |
| `list_relationship_types()` | Distinct relationship types (e.g. `RELATES_TO`, `MENTIONS`). |
| `sample_nodes(label?, limit?)` | A handful of node rows for orientation. |
| `search_facts(needle, limit?)` | Lexical substring search over `RELATES_TO.fact` — mirrors `/api/v1/entities/search`. |
| `graph_stats()` | Node count, edge count, label counts. |

All tools target a single tenant — set `MEANINGGRID_TENANT_ID` in the
environment. The server connects directly to FalkorDB (defaults match
`infra/docker-compose.yml`: `localhost:6380`).

## Run it

```bash
# from repo root
export MEANINGGRID_TENANT_ID=acme
uv run --package meaninggrid-mcp meaninggrid-mcp
```

Defaults to HTTP transport on `http://localhost:8765/mcp`. Override with:

| Env var | Default |
| --- | --- |
| `MCP_HOST` | `0.0.0.0` |
| `MCP_PORT` | `8765` |
| `FALKORDB_HOST` | `localhost` |
| `FALKORDB_PORT` | `6380` |
| `FALKORDB_USERNAME` | _(empty)_ |
| `FALKORDB_PASSWORD` | _(empty)_ |
| `MCP_CYPHER_TIMEOUT_MS` | `15000` |
| `MCP_MAX_ROWS` | `500` |

## Mutation guard

`read_cypher` rejects any query whose tokens (outside string literals and
comments) include any of: `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`,
`DROP`, `CALL`, `LOAD`, `FOREACH`. It also caps the row count via
`MCP_MAX_ROWS`. This is a safety net, not a sandbox — keep the FalkorDB
credentials read-only at the infra layer if you need a hard guarantee.
