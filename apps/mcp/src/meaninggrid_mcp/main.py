"""FastMCP server exposing read-only Cypher over the tenant's FalkorDB graph.

Run:
    uv run --package meaninggrid-mcp meaninggrid-mcp

Connects an agent at http://<MCP_HOST>:<MCP_PORT>/mcp (HTTP transport).
"""

from typing import Any

from fastmcp import FastMCP

from meaninggrid_mcp.falkor import run_cypher
from meaninggrid_mcp.guard import CypherWriteError, reject_writes
from meaninggrid_mcp.settings import settings

mcp: FastMCP = FastMCP(
    name="meaninggrid-graph",
    instructions=(
        "Read-only Cypher access to the tenant's knowledge graph (FalkorDB, "
        "populated by Graphiti). The graph has :Entity and :Episodic nodes, "
        "connected by :RELATES_TO (entity↔entity facts) and :MENTIONS "
        "(episode→entity). Prefer the schema helpers before writing a big "
        "Cypher query."
    ),
)


@mcp.tool
async def read_cypher(query: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a read-only Cypher query against the tenant's graph.

    Returns `{columns, rows, truncated}`. Mutations (CREATE/MERGE/SET/DELETE/
    REMOVE/DROP/CALL/LOAD/FOREACH) are rejected. Rows are capped — if
    `truncated` is true, narrow the query with `WHERE` / `LIMIT`.
    """
    try:
        reject_writes(query)
    except CypherWriteError as exc:
        return {"error": str(exc), "columns": [], "rows": [], "truncated": False}
    return await run_cypher(query, params)


@mcp.tool
async def list_labels() -> list[str]:
    """Distinct node labels in the tenant's graph (e.g. Entity, Episodic)."""
    result = await run_cypher(
        "MATCH (n) UNWIND labels(n) AS lbl RETURN DISTINCT lbl ORDER BY lbl",
        max_rows=1000,
    )
    return [r["lbl"] for r in result["rows"]]


@mcp.tool
async def list_relationship_types() -> list[str]:
    """Distinct relationship types (e.g. RELATES_TO, MENTIONS)."""
    result = await run_cypher(
        "MATCH ()-[r]->() RETURN DISTINCT type(r) AS rel ORDER BY rel",
        max_rows=1000,
    )
    return [r["rel"] for r in result["rows"]]


@mcp.tool
async def sample_nodes(label: str | None = None, limit: int = 5) -> dict[str, Any]:
    """A few example nodes for orientation. Pass `label` to filter."""
    limit = max(1, min(limit, 50))
    if label:
        query = "MATCH (n) WHERE $lbl IN labels(n) RETURN n LIMIT $limit"
    else:
        query = "MATCH (n) RETURN n LIMIT $limit"
    return await run_cypher(query, {"lbl": label, "limit": limit}, max_rows=limit)


@mcp.tool
async def search_facts(query: str, limit: int = 10) -> dict[str, Any]:
    """Substring search over RELATES_TO.fact — mirrors /api/v1/entities/search.

    `query` is a free-text needle matched against the fact string (case-insensitive).
    """
    limit = max(1, min(limit, 50))
    return await run_cypher(
        """
        MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
        WHERE toLower(r.fact) CONTAINS toLower($needle)
        RETURN r.fact AS fact, r.valid_at AS valid_at,
               a.name AS source, b.name AS target
        LIMIT $limit
        """,
        {"needle": query, "limit": limit},
        max_rows=limit,
    )


@mcp.tool
async def graph_stats() -> dict[str, Any]:
    """Node/edge counts and per-label node counts."""
    totals = await run_cypher(
        """
        MATCH (n) WITH count(n) AS node_count
        OPTIONAL MATCH ()-[r]->() WITH node_count, count(r) AS edge_count
        RETURN node_count, edge_count
        """,
        max_rows=1,
    )
    by_label = await run_cypher(
        """
        MATCH (n)
        UNWIND labels(n) AS lbl
        RETURN lbl, count(*) AS count
        ORDER BY count DESC
        """,
        max_rows=200,
    )
    row = totals["rows"][0] if totals["rows"] else {"node_count": 0, "edge_count": 0}
    return {
        "node_count": row.get("node_count", 0),
        "edge_count": row.get("edge_count", 0),
        "by_label": by_label["rows"],
    }


def run() -> None:
    if not settings.tenant_id:
        raise SystemExit(
            "MEANINGGRID_TENANT_ID is required — single-tenant per server instance."
        )
    mcp.run(transport="http", host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    run()
