"""LiftTextProcessor — promote a text field from event.data into artifacts["text"].

A lot of adapters land with a structured `event.data` containing one long
human-readable string (a transcript, an email body, a note) plus auxiliary
metadata. Without this processor, downstream embedding / summarisation
operates on the full JSON dump (incl. word-level timestamps, IDs, …) and the
signal is diluted by noise.

This processor:
- No-ops if a prior processor (e.g. ExtractTextProcessor on a blob) already
  set `artifacts["text"]`.
- Otherwise scans `event.data` for any of a small set of conventional text
  field names; the first non-empty string wins.
- Falls back to "longest string value" only if none of the known keys match,
  so JSON events without an obvious text column still get something useful.

See docs/architecture/ingestion-pipeline.md §9.3.
"""

import logging
from typing import Any

from meaninggrid_shared import IngestionContext

log = logging.getLogger("meaninggrid.worker.processors.lift_text")

# Ordered by preference — first hit wins. All lower-cased; comparison is case-insensitive.
_TEXT_KEYS = (
    "transcript",
    "text",
    "body",
    "content",
    "message",
    "summary",
    "description",
    "script",
    "dialogue",
)
_MIN_TEXT_LEN = 20  # avoid lifting a 3-char field over a longer JSON body


class LiftTextProcessor:
    name = "lift_text"
    requires: list[str] = []
    produces = ["text"]

    async def __call__(self, ctx: IngestionContext, next_):
        if ctx.artifacts.get("text"):
            return await next_()

        data = ctx.event.data
        if not isinstance(data, dict):
            return await next_()

        text = _find_text(data)
        if text and len(text) >= _MIN_TEXT_LEN:
            ctx.artifacts["text"] = text
        return await next_()


def _find_text(data: dict[str, Any]) -> str | None:
    """Best-effort text extraction from a JSON event payload."""
    lower_keys = {k.lower(): k for k in data.keys() if isinstance(k, str)}
    for key in _TEXT_KEYS:
        if key in lower_keys:
            v = data[lower_keys[key]]
            if isinstance(v, str) and v.strip():
                return v
            if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                return "\n".join(v)

    # Fallback: longest string value at the top level.
    longest = ""
    for v in data.values():
        if isinstance(v, str) and len(v) > len(longest):
            longest = v
    return longest or None
