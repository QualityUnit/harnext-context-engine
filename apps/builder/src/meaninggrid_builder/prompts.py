"""The builder agent's system prompt + per-lane instruction rendering.

The durable layout contract lives in the org FS (``CLAUDE.md``, auto-loaded).
The system prompt here carries the *behavioral* contract; the instruction
carries the *event(s)*. This separation is what lets the agent be stateless yet
consistent across builds.
"""

from __future__ import annotations

import json

from meaninggrid_builder.work_item import WorkItem

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

Edit only files under the working directory. Do not run shell commands or access
the network. Cite the event id/source in provenance. Do not invent facts beyond
the payload. Make the minimal set of edits that fully and faithfully incorporates
the event(s), then stop.
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


def render_instruction(wi: WorkItem) -> str:
    if wi.lane == "fast":
        ev = wi.events[0]
        return _FAST_TMPL.format(subject=ev.subject, event_json=ev.model_dump_json(indent=2))
    events_json = json.dumps([e.model_dump(mode="json") for e in wi.events], indent=2, default=str)
    return _BATCH_TMPL.format(
        n=len(wi.events), subjects=", ".join(wi.subjects), events_json=events_json
    )
