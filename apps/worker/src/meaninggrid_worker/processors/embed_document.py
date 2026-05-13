"""EmbedDocumentProcessor — one document-level embedding per event.

Embeds artifacts["text"] when ExtractTextProcessor produced it; otherwise falls
back to a canonical JSON form of event.data so every event lands on the FAISS
map (not just file uploads).

Adds:
    artifacts["embedding"]         — np.ndarray float32 (dim,), L2-normalized
    artifacts["embedding_preview"] — short string for viz tooltips

See docs/architecture/ingestion-pipeline.md §9.3 (Processor contract) and §9.9
(worked example for a vector sink).
"""

import json
import logging

import numpy as np
from meaninggrid_shared import IngestionContext

from meaninggrid_worker.embedder import get_embedder

log = logging.getLogger("meaninggrid.worker.processors.embed_document")

# nomic-embed-text and most local embedders have small context windows.
# A hard cap keeps a 1MB transcript from blowing up the request.
_MAX_CHARS = 8000
_PREVIEW_CHARS = 280


class EmbedDocumentProcessor:
    name = "embed_document"
    requires: list[str] = []
    produces = ["embedding", "embedding_preview"]

    async def __call__(self, ctx: IngestionContext, next_):
        body = ctx.artifacts.get("text") or json.dumps(
            ctx.event.data or {}, default=str, sort_keys=True
        )
        body = body.strip()
        if not body:
            log.debug("event %s: empty body, no embedding", ctx.event.id)
            return await next_()

        truncated = body[:_MAX_CHARS]
        try:
            vec = await get_embedder().create(input_data=truncated)
        except Exception as e:
            log.warning("embedding failed for event %s: %s", ctx.event.id, e)
            return await next_()

        arr = np.asarray(vec, dtype=np.float32)
        norm = float(np.linalg.norm(arr))
        if norm > 0:
            arr = arr / norm  # cosine via IndexFlatIP
        ctx.artifacts["embedding"] = arr
        ctx.artifacts["embedding_preview"] = body[:_PREVIEW_CHARS]
        return await next_()
