"""Graph + entity read endpoints.

Backed by FalkorDB directly (Graphiti's high-level retrieve_episodes only
switches to per-group graphs when len(group_ids) > 1, which we don't hit with
single-tenant queries — so we clone the driver to the tenant's graph and run
Cypher directly).

Wire shape per dashboard.md §6: {nodes, edges} consumable by Cytoscape.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from meaninggrid_api.auth import get_tenant_id
from meaninggrid_api.graphiti_client import get_graphiti

router = APIRouter(prefix="/api/v1", tags=["graph"])


class GraphNode(BaseModel):
    id: str
    kind: str
    name: str
    summary: str | None = None
    labels: list[str] = []
    valid_at: datetime | None = None
    invalid_at: datetime | None = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    fact: str
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    episode_uuid: str | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def _parse_dt(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    last_n: int | None = Query(
        None,
        ge=1,
        le=10_000,
        description=(
            "Optional cap on episodes. Omit to return every entity + edge for the "
            "tenant — narrowing happens client-side via the filter panel."
        ),
    ),
) -> GraphResponse:
    """Default: return the tenant's entire entity-fact subgraph (all entities and
    all RELATES_TO edges Graphiti has extracted). Pass `?last_n=N` to narrow to
    the subgraph induced by the most recent N episodes — useful for big graphs
    where the UI can't handle thousands of nodes.
    """
    driver = get_graphiti().driver.clone(database=tenant_id)

    if last_n is None:
        # No episode filter — return all entities + all RELATES_TO edges.
        node_records, _, _ = await driver.execute_query(
            """
            MATCH (n:Entity)
            RETURN
                n.uuid AS id, n.name AS name, n.summary AS summary,
                labels(n) AS labels, n.created_at AS created_at
            """,
        )
        edge_records, _, _ = await driver.execute_query(
            """
            MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
            RETURN
                r.uuid AS id, a.uuid AS source, b.uuid AS target, r.fact AS fact,
                r.valid_at AS valid_at, r.invalid_at AS invalid_at, r.episodes AS episodes
            """,
        )
    else:
        ep_records, _, _ = await driver.execute_query(
            """
            MATCH (e:Episodic)
            WHERE e.valid_at <= $ref_time
            RETURN e.uuid AS uuid
            ORDER BY e.valid_at DESC
            LIMIT $limit
            """,
            ref_time=datetime.now(UTC),
            limit=last_n,
        )
        episode_uuids = [r["uuid"] for r in (ep_records or [])]
        if not episode_uuids:
            return GraphResponse(nodes=[], edges=[])

        node_records, _, _ = await driver.execute_query(
            """
            MATCH (ep:Episodic)-[:MENTIONS]->(n:Entity)
            WHERE ep.uuid IN $uuids
            RETURN DISTINCT
                n.uuid AS id, n.name AS name, n.summary AS summary,
                labels(n) AS labels, n.created_at AS created_at
            """,
            uuids=episode_uuids,
        )
        edge_records, _, _ = await driver.execute_query(
            """
            MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
            WHERE r.episodes IS NOT NULL AND any(eid IN r.episodes WHERE eid IN $uuids)
            RETURN
                r.uuid AS id, a.uuid AS source, b.uuid AS target, r.fact AS fact,
                r.valid_at AS valid_at, r.invalid_at AS invalid_at, r.episodes AS episodes
            """,
            uuids=episode_uuids,
        )

    nodes = [
        GraphNode(
            id=str(r["id"]),
            kind="entity",
            name=str(r.get("name") or ""),
            summary=r.get("summary"),
            labels=list(r.get("labels") or []),
            valid_at=_parse_dt(r.get("created_at")),
        )
        for r in (node_records or [])
    ]
    edges = [
        GraphEdge(
            id=str(r["id"]),
            source=str(r["source"]),
            target=str(r["target"]),
            fact=str(r.get("fact") or ""),
            valid_at=_parse_dt(r.get("valid_at")),
            invalid_at=_parse_dt(r.get("invalid_at")),
            episode_uuid=(r.get("episodes") or [None])[0] if r.get("episodes") else None,
        )
        for r in (edge_records or [])
    ]
    return GraphResponse(nodes=nodes, edges=edges)


class EntitySearchHit(BaseModel):
    fact: str
    valid_at: datetime | None
    source_node: str
    target_node: str


@router.get("/entities/search", response_model=list[EntitySearchHit])
async def search_entities(
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> list[EntitySearchHit]:
    """Lexical fact search via Cypher CONTAINS over the tenant's graph.

    v0: simple substring match. Replace with Graphiti.search() once we work
    around the multi-tenant routing limitation, or with a vector search
    against `r.fact_embedding` directly.
    """
    driver = get_graphiti().driver.clone(database=tenant_id)
    records, _, _ = await driver.execute_query(
        """
        MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
        WHERE toLower(r.fact) CONTAINS toLower($needle)
        RETURN r.fact AS fact, r.valid_at AS valid_at,
               a.uuid AS source_node, b.uuid AS target_node
        LIMIT $limit
        """,
        needle=q,
        limit=limit,
    )
    return [
        EntitySearchHit(
            fact=str(r.get("fact") or ""),
            valid_at=_parse_dt(r.get("valid_at")),
            source_node=str(r.get("source_node") or ""),
            target_node=str(r.get("target_node") or ""),
        )
        for r in (records or [])
    ]
