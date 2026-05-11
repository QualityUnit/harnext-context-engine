"""ExtractTextProcessor — for blob events (file uploads), pull bytes from MinIO and extract text.

Routes by mime type:
    application/pdf    → pypdf
    text/*             → utf-8 decode (fallback latin-1)
    other              → skip; downstream sinks may still consume event.data

Adds artifacts["text"] when extraction succeeds.
See docs/architecture/ingestion-pipeline.md §9.3.
"""

import io
import logging

from pypdf import PdfReader

from meaninggrid_shared import IngestionContext
from meaninggrid_worker.storage import fetch_blob

log = logging.getLogger("meaninggrid.worker.processors.extract_text")


class ExtractTextProcessor:
    name = "extract_text"
    requires: list[str] = []
    produces = ["text"]

    async def __call__(self, ctx: IngestionContext, next_):
        blob_ref = ctx.event.mgblobref
        if not blob_ref:
            return await next_()

        try:
            body = await fetch_blob(blob_ref)
        except Exception as e:
            log.warning("failed to fetch blob %s: %s", blob_ref, e)
            return await next_()

        mime = (ctx.event.data or {}).get("mime", "") if ctx.event.data else ""
        text = self._extract(body, mime)
        if text:
            ctx.artifacts["text"] = text
        return await next_()

    @staticmethod
    def _extract(body: bytes, mime: str) -> str | None:
        if mime == "application/pdf":
            try:
                reader = PdfReader(io.BytesIO(body))
                return "\n\n".join(p.extract_text() or "" for p in reader.pages).strip()
            except Exception as e:
                log.warning("pdf extract failed: %s", e)
                return None
        if mime.startswith("text/") or mime in {"application/json", "application/xml"}:
            try:
                return body.decode("utf-8")
            except UnicodeDecodeError:
                return body.decode("latin-1", errors="replace")
        return None
