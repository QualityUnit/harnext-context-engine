"""The builder agent's system prompt + per-lane instruction rendering.

The durable layout contract lives in the org FS (``CLAUDE.md``, auto-loaded).
The system prompt here carries the *behavioral* contract; the instruction
carries the *event(s)*. This separation is what lets the agent be stateless yet
consistent across builds.
"""

from __future__ import annotations

import json

from harnext_shared import CloudEvent

from harnext_builder.event_fs import rel_for
from harnext_builder.work_item import WorkItem

SYSTEM_PROMPT = """\
You are a context-maintenance agent. Your working directory is one
organization's living context filesystem. Read `CLAUDE.md` and `_meta/schema.md`
first — they define the layout and your procedure. Incorporate the event(s) in
the user message into the filesystem:

- File each event under the right entity directory (`entities/<type>/<slug>/`),
  derived from the event `subject`.
- Append a dated, sourced line to that entity's `timeline.md` (audit trail —
  never rewrite history).
- Keep each entity's `OVERVIEW.md` a concise, current synthesis.
- Dedupe and supersede: do not duplicate known facts; move contradicted facts to
  `_meta/superseded.md` with a pointer + reason; write the new fact in `facts.md`.
- Keep the top-level `INDEX.md` accurate.

For a GitHub commit/PR event, the changed source files are mounted read-only
under `_event/` (see `_event/MANIFEST.md`). Read them to understand what actually
changed — the event JSON lists the files but omits their content. `_event/` is
reference material only: never edit it, never copy file bodies into the context
verbatim, and don't file it as an entity. It is removed after this build.

Edit only files under the working directory (excluding `_event/`). Do not run
shell commands or access the network. Cite the event id/source in provenance. Do
not invent facts beyond the payload. Make the minimal set of edits that fully and
faithfully incorporates the event(s), then stop.
"""

_FAST_TMPL = """\
A new event (routed FAST — signal-grade / anomalous) arrived for entity \
`{subject}`. Incorporate it now, and make sure its significance is reflected in \
the entity's `OVERVIEW.md`, not buried only in the timeline.

```json
{event_json}
```
"""

_BATCH_TMPL = """\
A batch window closed for this organization: {n} event(s) for entity \
`{subjects}`. Incorporate them as one coherent update — dedupe aggressively \
across the window and synthesize rather than transcribe.

```json
{events_json}
```
"""


def _redact(ev: CloudEvent) -> dict:
    """Event as JSON for the prompt, but with each changed file's content replaced
    by a pointer to where it's mounted — the agent reads the body from `_event/`,
    keeping the prompt small."""
    d = ev.model_dump(mode="json")
    files = (d.get("data") or {}).get("files")
    if isinstance(files, list):
        for f in files:
            if f.get("content") is not None:
                f["content"] = f"<see {rel_for(ev.id, f.get('path', ''))}>"
    return d


def render_instruction(wi: WorkItem) -> str:
    if wi.lane == "fast":
        ev = wi.events[0]
        event_json = json.dumps(_redact(ev), indent=2, default=str)
        return _FAST_TMPL.format(subject=ev.subject, event_json=event_json)
    events_json = json.dumps([_redact(e) for e in wi.events], indent=2, default=str)
    return _BATCH_TMPL.format(
        n=len(wi.events), subjects=", ".join(wi.subjects), events_json=events_json
    )
