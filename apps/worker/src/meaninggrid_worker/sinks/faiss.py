"""FaissSink — per-tenant on-disk FAISS vector store.

Implements §9.9 of docs/architecture/ingestion-pipeline.md (the worked example
for a vector sink). Each tenant gets its own `{faiss_dir}/{tenant}.index` file
plus a SQLite sidecar row in `vector_documents` so the API can render points
without re-reading the FAISS file end-to-end.

v0 choices:
- IndexFlatIP, exact NN over L2-normalized vectors → cosine similarity. Fine
  up to ~100k docs/tenant on commodity hardware; swap for IVF/HNSW later
  without changing the contract.
- One file per tenant. With multiple worker processes (Kafka partition-fanout),
  cross-process safety is provided by an advisory `fcntl.flock` on a sidecar
  `.lock` file held across the read-modify-write window. The per-process
  asyncio.Lock is still useful to avoid intra-process re-entry.
- Idempotent on event.id: presence of a VectorDocument row → skip.
"""

import asyncio
import fcntl
import logging
import os
from pathlib import Path

import faiss  # type: ignore[import-untyped]
import numpy as np
from meaninggrid_shared import IngestionContext, VectorDocument

from meaninggrid_worker.db import SessionLocal
from meaninggrid_worker.settings import settings

log = logging.getLogger("meaninggrid.worker.sinks.faiss")


class FaissSink:
    name = "faiss"
    requires = ["embedding"]

    def __init__(self) -> None:
        self._dir = Path(settings.faiss_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def _index_path(self, tenant_id: str) -> Path:
        return self._dir / f"{tenant_id}.index"

    def _lock(self, tenant_id: str) -> asyncio.Lock:
        lk = self._locks.get(tenant_id)
        if lk is None:
            lk = asyncio.Lock()
            self._locks[tenant_id] = lk
        return lk

    async def write(self, ctx: IngestionContext) -> None:
        vec = ctx.artifacts.get("embedding")
        if vec is None:
            # Embedder failed or the body was empty. Treat as a no-op success
            # so dedup marks this event done and we don't loop on it.
            log.debug("event %s: no embedding artifact, skipping", ctx.event.id)
            return

        arr = np.asarray(vec, dtype=np.float32).reshape(1, -1)
        dim = int(arr.shape[1])
        tenant_id = ctx.event.mgtenant
        event_id = ctx.event.id

        async with self._lock(tenant_id):
            async with SessionLocal() as session:
                existing = await session.get(VectorDocument, (tenant_id, event_id))
                if existing is not None:
                    log.debug(
                        "event %s already in faiss (faiss_id=%d)",
                        event_id,
                        existing.faiss_id,
                    )
                    return

                path = self._index_path(tenant_id)
                faiss_id = await asyncio.to_thread(_append_and_persist, path, arr, dim)

                session.add(
                    VectorDocument(
                        tenant_id=tenant_id,
                        event_id=event_id,
                        faiss_id=faiss_id,
                        dim=dim,
                        source=ctx.event.source,
                        type=ctx.event.type,
                        subject=ctx.event.subject,
                        event_time=ctx.event.time,
                        ingest_time=ctx.event.mgingesttime or ctx.event.time,
                        text_preview=ctx.artifacts.get("embedding_preview"),
                    )
                )
                await session.commit()
                log.info(
                    "faiss: tenant=%s event=%s faiss_id=%d dim=%d",
                    tenant_id,
                    event_id,
                    faiss_id,
                    dim,
                )


def _append_and_persist(path: Path, arr: np.ndarray, dim: int) -> int:
    """Synchronous: load (or create) the index, append, atomic-write back.

    Runs via asyncio.to_thread so we don't block the event loop on disk I/O.

    Cross-process safety: held under an exclusive `fcntl.flock` on a sidecar
    `.lock` file so concurrent worker processes can't race read-modify-write
    on the same tenant's index. Advisory locks are sufficient because every
    writer goes through this function (and `flock` is honored only by callers
    that also take it).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    # Open in append mode so the file is created if missing and we don't
    # truncate anything. We never write to lock_f — only use it as a flock
    # target.
    with open(lock_path, "a") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            if path.exists():
                idx = faiss.read_index(str(path))
                if idx.d != dim:
                    raise ValueError(
                        f"FAISS index at {path} has dim={idx.d}, incoming embedding has dim={dim}"
                    )
            else:
                idx = faiss.IndexFlatIP(dim)

            new_id = int(idx.ntotal)
            idx.add(arr)

            tmp = path.with_suffix(path.suffix + ".tmp")
            faiss.write_index(idx, str(tmp))
            os.replace(tmp, path)
            return new_id
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
