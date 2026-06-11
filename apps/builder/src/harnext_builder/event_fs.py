"""The ``_event/`` mount — changed source files for the triggering event(s).

A GitHub commit/PR event carries its changed files in ``data["files"]`` (fetched
at ingest, where the repo token lives). The builder agent is network-isolated, so
it can't fetch them itself. This module is the single source of truth for how
those files are laid out in the agent's working directory:

    _event/
      MANIFEST.md                      # human index: every event + its files
      <event-id>/<original/path.py>    # full content of each changed file

The runner writes this tree before a build, points the agent at it, and removes
it afterwards (it is excluded from the FS diff and never snapshotted — it's
reference material, not durable context). ``prompts.py`` uses :func:`rel_for` to
tell the agent exactly where each file landed.
"""

from __future__ import annotations

import re

from harnext_shared import CloudEvent

from harnext_builder.harness.base import EventFile

EVENT_DIR = "_event"
MANIFEST = f"{EVENT_DIR}/MANIFEST.md"

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_id(event_id: str) -> str:
    """A filesystem-safe directory name for an event id."""
    return _SAFE.sub("_", event_id).strip("_") or "event"


def _safe_relpath(path: str) -> str | None:
    """Reject absolute paths and ``..`` traversal; normalize separators."""
    p = path.strip().lstrip("/")
    if not p or ".." in p.split("/"):
        return None
    return p


def rel_for(event_id: str, path: str) -> str:
    """Where a changed file lands under the working dir."""
    return f"{EVENT_DIR}/{safe_id(event_id)}/{path}"


def has_files(ev: CloudEvent) -> bool:
    files = (ev.data or {}).get("files")
    return isinstance(files, list) and any(f.get("content") is not None for f in files)


def event_files(events: list[CloudEvent]) -> list[EventFile]:
    """Flatten the changed files across ``events`` into the ``_event/`` tree,
    plus a MANIFEST. Returns an empty list when no event carries file content."""
    out: list[EventFile] = []
    manifest_lines = ["# Changed files for this build", ""]
    any_content = False

    for ev in events:
        files = (ev.data or {}).get("files")
        if not isinstance(files, list) or not files:
            continue
        manifest_lines.append(f"## {ev.type} — `{ev.subject}` ({ev.id})")
        for f in files:
            path = _safe_relpath(str(f.get("path") or ""))
            status = f.get("status", "?")
            if path is None:
                continue
            content = f.get("content")
            if content is not None:
                rel = rel_for(ev.id, path)
                out.append(EventFile(path=rel, content=content))
                trunc = " (truncated)" if f.get("truncated") else ""
                manifest_lines.append(f"- `{status}` [{path}]({rel}){trunc}")
                any_content = True
            else:
                # removed or binary — listed for context, no file written
                manifest_lines.append(f"- `{status}` {path} _(no content)_")
        manifest_lines.append("")

    if not any_content:
        return []
    out.append(EventFile(path=MANIFEST, content="\n".join(manifest_lines)))
    return out
