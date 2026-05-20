"""Thin wrapper over the async FalkorDB client.

Tenancy: one FalkorDB graph (database) per tenant — same convention used by
the worker and `apps/api/.../graph.py` (which calls `driver.clone(database=tenant_id)`).
"""

from collections.abc import Mapping
from typing import Any

from falkordb.asyncio import FalkorDB

from meaninggrid_mcp.settings import settings

_db: FalkorDB | None = None


def _client() -> FalkorDB:
    global _db
    if _db is None:
        _db = FalkorDB(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            username=settings.falkordb_username or None,
            password=settings.falkordb_password or None,
        )
    return _db


def _serialize(value: Any) -> Any:
    """Convert FalkorDB Node/Edge/Path objects into plain JSON-safe dicts."""
    # Nodes and edges expose a `.properties` mapping plus identifying attrs.
    properties = getattr(value, "properties", None)
    if properties is not None:
        out: dict[str, Any] = {"_props": {k: _serialize(v) for k, v in properties.items()}}
        for attr in ("id", "labels", "label", "relation", "src_node", "dest_node"):
            v = getattr(value, attr, None)
            if v is not None:
                out[attr] = _serialize(v)
        return out
    if isinstance(value, Mapping):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_serialize(v) for v in value]
    # Primitives + anything else falls through to whatever the JSON encoder makes of it.
    return value


def _column_name(header_entry: Any) -> str:
    # falkordb-py historically returns (type, name) tuples; newer versions may
    # return plain strings. Handle both.
    if isinstance(header_entry, tuple | list) and len(header_entry) >= 2:
        return str(header_entry[1])
    return str(header_entry)


async def run_cypher(
    query: str,
    params: dict[str, Any] | None = None,
    *,
    tenant_id: str | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Execute Cypher against the tenant's graph; return columns + rows.

    Returned shape: {"columns": [str, ...], "rows": [{col: value, ...}, ...],
    "truncated": bool}.
    """
    tenant = tenant_id or settings.tenant_id
    if not tenant:
        raise RuntimeError(
            "No tenant configured. Set MEANINGGRID_TENANT_ID before starting the server."
        )

    graph = _client().select_graph(tenant)
    result = await graph.query(query, params or {}, timeout=settings.mcp_cypher_timeout_ms)

    header = getattr(result, "header", None) or []
    columns = [_column_name(h) for h in header]
    raw_rows = getattr(result, "result_set", None) or []

    cap = max_rows if max_rows is not None else settings.mcp_max_rows
    truncated = len(raw_rows) > cap
    rows = [
        {col: _serialize(val) for col, val in zip(columns, row, strict=False)}
        for row in raw_rows[:cap]
    ]
    return {"columns": columns, "rows": rows, "truncated": truncated}
