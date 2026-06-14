# Skills — project-scoped agent instructions

A **skill** is a named directory of files — a mandatory `SKILL.md` entry file
plus any supporting files (reference docs, scripts, templates) — that teaches an
agent how to do something the way your team does it. Skills are
**project-scoped**: they belong to a project (the tenant) and are shared by
everyone in the company through that project's Context Engine. One definition,
consumed everywhere:

- the **dashboard / ingest API** is where skills are created and edited,
- the **MCP server** serves them to *external* agents as `skill://` resources
  (the FastMCP skill resource protocol), scoped to the bearer token's org,
- **internal** builder/research agents get them materialized automatically as
  `.claude/skills/<name>/` inside their working directory.

## Anatomy of a skill

```
release-api/
├── SKILL.md          # required entry file
├── reference.md
└── scripts/
    └── tag.py
```

- **Name** — a slug matching `^[a-z0-9][a-z0-9_-]{0,63}$`. It doubles as the
  directory name and the `skill://` host, and is unique per project.
- **File paths** — relative POSIX paths (`SKILL.md`, `scripts/tag.py`): no
  leading `/`, no `..`, no `\`, and `_manifest` is reserved. Every skill must
  contain a file at exactly `SKILL.md`.

## The `SKILL.md` format

The entry file is markdown, optionally with YAML frontmatter. The skill's
**description** — what listings show and what agents read to decide when to use
the skill — is resolved in order from:

1. an explicit `description` given to the API,
2. the `description` key of the `SKILL.md` frontmatter,
3. the first non-heading line of the `SKILL.md` body.

```markdown
---
description: Release a new version of the API following our checklist.
---

# release-api

1. Bump the version in `pyproject.toml`.
2. Run `scripts/tag.py` to tag and push.
```

## Managing skills (ingest API)

Skill CRUD lives on the ingest API (`:8000`) next to the rest of the
project-scoped routes: authenticate with the dashboard session token
(`Authorization: Bearer <token>`); every call is checked against project
ownership.

| Method & path | What |
|---|---|
| `POST /skills` | create — body `{project_id, name, description?, files}` |
| `GET /skills?project_id={id}` | list a project's skills — file metadata only (`path`, `size`, `hash`, `mime_type`), no content |
| `GET /skills/{skill_id}` | one skill **with** file content |
| `PUT /skills/{skill_id}` | update — `description` and/or a full file-set replacement when `files` is given |
| `DELETE /skills/{skill_id}` | delete the skill and its files |

Each entry in `files` is `{path, content, encoding}` with `encoding` either
`"utf-8"` (content is the text itself) or `"base64"` (binary files). The server
computes each file's `mime_type`, `size`, and `sha256:` hash; responses return
text files with `encoding: "utf-8"` and everything else as `"base64"`.

```bash
curl -s localhost:8000/skills \
  -H "Authorization: Bearer $SESSION" -H 'Content-Type: application/json' -d '{
    "project_id": "'$PROJECT'",
    "name": "release-api",
    "files": [
      {"path": "SKILL.md",
       "content": "---\ndescription: Release a new version of the API.\n---\n# release-api\n…",
       "encoding": "utf-8"}
    ]
  }'
```

A `PUT` with `files` replaces the skill's entire file set under the same
validation (`SKILL.md` must still be present). Deleting a project deletes its
skills along with everything else it owns.

## MCP exposure — the `skill://` scheme

The MCP server (`:8765`, the same per-project bearer token as the context
tools) lists and serves the token org's skills using the FastMCP skill resource
protocol:

| URI | Content |
|---|---|
| `skill://{name}/SKILL.md` | the entry file (`text/markdown`); the resource's `description` is the skill's description — this is what skill listings read |
| `skill://{name}/_manifest` | `application/json`: `{"skill": "<name>", "files": [{"path", "size", "hash"}]}` — **all** files, `SKILL.md` included |
| `skill://{name}/{path}` | every file readable at its own URI — text mime types as text, everything else as binary (blob) |

All listing and reads are scoped to the org of the request's verified bearer
token: a token for org A can never see or read org B's skills, including via a
direct `read_resource` on a guessed URI.

## Consuming skills from any FastMCP client

`fastmcp.utilities.skills` speaks this protocol out of the box —
`list_skills`, `get_skill_manifest`, `download_skill`, and `sync_skills`. To
pull every skill of a project into `~/.claude/skills` (where Claude Code picks
them up):

```python
import asyncio

from fastmcp import Client
from fastmcp.utilities.skills import sync_skills

MCP_URL = "http://localhost:8765/mcp"  # or https://app.harnext.dev/mcp
TOKEN = "..."  # the project's MCP token (dashboard → Connect)


async def main() -> None:
    async with Client(MCP_URL, auth=TOKEN) as client:
        paths = await sync_skills(client, "~/.claude/skills")
        print(f"synced {len(paths)} skill(s): {', '.join(p.name for p in paths)}")


asyncio.run(main())
```

`sync_skills` skips skill directories that already exist locally; pass
`overwrite=True` to replace them.

## Automatic injection into internal agents

Internal agents need no MCP round-trip: before a run, the project's skills are
materialized straight from the database into the agent's working directory as
`.claude/skills/{name}/{path}` (via `harnext_shared.materialize_skills`, with
path-traversal-unsafe rows skipped). The harness discovers them natively — the
builder agent incorporating events and the MCP research/update agents all work
with the same skills the rest of the company shares.
