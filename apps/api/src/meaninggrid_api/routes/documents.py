"""Document map — per-tenant 2D scatter of FAISS-stored document embeddings.

Reads the per-tenant `{faiss_dir}/{tenant}.index` written by FaissSink
(see apps/worker/sinks/faiss.py and docs/architecture/ingestion-pipeline.md
§9.9). Projects vectors to 2D via PCA (numpy SVD; no sklearn dependency) and
returns one point per document for the frontend scatter view.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

import faiss  # type: ignore[import-untyped]
import numpy as np
from fastapi import APIRouter, Depends, Query
from meaninggrid_shared import VectorDocument
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meaninggrid_api.auth import get_tenant_id
from meaninggrid_api.db import get_session
from meaninggrid_api.settings import settings

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
log = logging.getLogger("meaninggrid.api.documents")


class DocumentPoint(BaseModel):
    event_id: str
    source: str
    type: str
    subject: str
    event_time: datetime
    ingest_time: datetime
    text_preview: str | None
    x: float
    y: float


class DocumentMap(BaseModel):
    points: list[DocumentPoint]
    method: str
    variance_explained: list[float]  # ratio for components 1 and 2; sums to ≤ 1


@router.get("/vectors", response_model=DocumentMap)
async def get_document_map(
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(500, ge=1, le=5000),
) -> DocumentMap:
    rows = (
        await session.execute(
            select(VectorDocument)
            .where(VectorDocument.tenant_id == tenant_id)
            .order_by(VectorDocument.ingest_time.desc())
            .limit(limit)
        )
    ).scalars().all()
    if not rows:
        return DocumentMap(points=[], method="pca", variance_explained=[0.0, 0.0])

    # Chronological so the frontend can colour by recency without re-sorting.
    rows = list(reversed(rows))

    index_path = Path(settings.faiss_dir) / f"{tenant_id}.index"
    if not index_path.exists():
        log.warning("vector_documents has rows but FAISS index missing at %s", index_path)
        return DocumentMap(points=[], method="pca", variance_explained=[0.0, 0.0])

    coords, var_ratio = await asyncio.to_thread(
        _project_pca,
        str(index_path),
        [r.faiss_id for r in rows],
    )

    points = [
        DocumentPoint(
            event_id=r.event_id,
            source=r.source,
            type=r.type,
            subject=r.subject,
            event_time=r.event_time,
            ingest_time=r.ingest_time,
            text_preview=r.text_preview,
            x=float(coords[i, 0]),
            y=float(coords[i, 1]),
        )
        for i, r in enumerate(rows)
    ]
    return DocumentMap(points=points, method="pca", variance_explained=var_ratio)


def _project_pca(index_path: str, faiss_ids: list[int]) -> tuple[np.ndarray, list[float]]:
    """Reconstruct vectors for the requested FAISS ids, project to 2D via PCA."""
    index = faiss.read_index(index_path)
    dim = index.d
    n = len(faiss_ids)

    vecs = np.zeros((n, dim), dtype=np.float32)
    for i, fid in enumerate(faiss_ids):
        vecs[i] = index.reconstruct(int(fid))

    if n < 2:
        return np.zeros((n, 2), dtype=np.float32), [0.0, 0.0]

    centered = vecs - vecs.mean(axis=0, keepdims=True)
    _, s, vt = np.linalg.svd(centered, full_matrices=False)
    components = vt[:2]                # (2, dim)
    coords = centered @ components.T   # (n, 2)

    total_var = float((s ** 2).sum())
    if total_var > 0:
        var_ratio = [float((s[0] ** 2) / total_var), float((s[1] ** 2) / total_var)]
    else:
        var_ratio = [0.0, 0.0]
    return coords.astype(np.float32, copy=False), var_ratio
