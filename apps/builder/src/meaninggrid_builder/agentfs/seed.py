"""The initial on-FS layout for a fresh org context filesystem.

These files are written once at genesis and then maintained by the builder
agent on every incorporation. ``CLAUDE.md`` is auto-loaded by Claude Code from
the working directory, so it carries the durable layout contract (surviving
even if the per-build prompts change).
"""

CLAUDE_MD = """# Context Filesystem — Operating Manual

You are a **context-maintenance agent**. This working directory is one
organization's living, durable memory, distilled from a stream of events
(GitHub, Slack, …). Your sole job is to **incorporate newly arrived events**
into these files so that a future agent can answer questions about the org by
reading them. You are not a chat assistant; you only edit files.

## Layout (keep to it)

```
INDEX.md                         top-level index: every entity + last-updated date
entities/<type>/<slug>/          one directory per event subject (e.g. repo:acme/web)
    OVERVIEW.md                  concise CURRENT state of this entity (rewrite to keep current)
    facts.md                     atomic, dated, sourced facts (supersede, don't duplicate)
    timeline.md                  append-only dated provenance log (never rewrite history)
topics/<slug>.md                 cross-entity themes you choose to maintain
_meta/schema.md                  these conventions (so a future agent re-derives them)
_meta/superseded.md              retired facts, with a pointer to what replaced them
```

The event `subject` maps to an entity directory: `repo:acme/web` →
`entities/repo/acme__web/`, `channel:general` → `entities/channel/general/`.
Slugify by replacing `/` with `__` and `:` with `/` after the type.

## Procedure for each event

1. **Locate or create** the entity directory from the event `subject`.
2. **Append** a dated, sourced line to that entity's `timeline.md`
   (`- <ISO date> [<source>#<id>] <what happened>`). This is the audit trail —
   never edit or delete past lines.
3. **Update `OVERVIEW.md`** to reflect the new current state: concise, current,
   no duplication. Rewrite freely.
4. **Dedupe & supersede.** If the event restates a known fact, do not duplicate.
   If it contradicts/updates a fact in `facts.md`, move the old fact to
   `_meta/superseded.md` with a pointer + reason, and write the new fact.
5. **Maintain `INDEX.md`** so every entity and its last-updated date is listed.

## Rules

- Edit only files under this directory. Do not run shell commands or access the
  network. Do not delete entity directories or `timeline.md` history.
- Cite the event id/source in provenance. Do not invent facts unsupported by the
  event payload. Make the minimal set of edits that fully and faithfully
  incorporates the event(s). Stop when incorporation is complete.
"""

INDEX_MD = """# Org Context Index

_Maintained by the builder agent. One line per entity with its last-updated date._

| Entity | Type | Last updated | Overview |
|--------|------|--------------|----------|
"""

SCHEMA_MD = """# On-FS Conventions

- `entities/<type>/<slug>/` — one directory per event `subject`.
  - `OVERVIEW.md` — current synthesized state (rewrite to keep current).
  - `facts.md` — atomic, dated, sourced facts; supersede rather than duplicate.
  - `timeline.md` — append-only provenance (`- <ISO date> [<source>#<id>] <text>`).
- `topics/<slug>.md` — cross-entity themes.
- `_meta/superseded.md` — retired facts with pointers to their replacements.
- `INDEX.md` — top-level navigation; keep entity list + last-updated current.

Provenance and supersession (not deletion) make this store auditable: the
timeline is the system of record; OVERVIEW/facts are the current projection.
"""

SUPERSEDED_MD = """# Superseded Facts

_When a fact is updated or contradicted, the old version is moved here with a
pointer to its replacement and the event that triggered the change._
"""

# relpath -> content. Directories are created implicitly by the file writes.
SEED_FILES: dict[str, str] = {
    "CLAUDE.md": CLAUDE_MD,
    "INDEX.md": INDEX_MD,
    "_meta/schema.md": SCHEMA_MD,
    "_meta/superseded.md": SUPERSEDED_MD,
    "entities/.gitkeep": "",
    "topics/.gitkeep": "",
}
