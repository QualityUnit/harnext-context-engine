"""The ``.claude/skills/`` mount — the org's project Skills for the agent.

Skills live in the metadata DB (managed via the ingest API / web UI), not in
the org context FS. Before a build, the BuildRunner stages them with
``harnext_shared.materialize_skills`` and ships them in the HarnessRequest
(the real working dir only exists inside the runner subprocess — for AgentFS
it is a transient ``agentfs exec`` mount). The runner writes them under
``.claude/skills/{name}/`` in the working dir, where the coding harness
(``setting_sources=["project"]``) auto-loads them.

Like ``_event/``, the mount is reference material, not durable context: the
runner excludes the subtree from the files_changed diff and removes it before
the post-build snapshot, so materialized skills never enter the org context
store as if the agent created them. The flip side is deliberate too — the
``.claude/skills/`` subtree is reserved for the DB-backed mount, so nothing
under it (even agent-written) survives a build; the DB is the only source of
skills.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from harnext_shared import materialize_skills
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harnext_builder.harness.base import SkillMountFile

SKILLS_DIR = ".claude/skills"


async def skill_mount_files(
    sm: async_sessionmaker[AsyncSession], org_id: str
) -> list[SkillMountFile]:
    """Stage the org's skills via ``materialize_skills`` and pack them for the
    HarnessRequest. Returns an empty list when the org has no skills."""
    out: list[SkillMountFile] = []
    with tempfile.TemporaryDirectory(prefix=f"skills-{org_id}-") as tmp:
        await materialize_skills(sm, org_id, tmp)
        root = Path(tmp) / SKILLS_DIR
        if not root.is_dir():
            return []
        for p in sorted(root.rglob("*")):
            if p.is_file():
                out.append(
                    SkillMountFile(
                        path=f"{SKILLS_DIR}/{p.relative_to(root).as_posix()}",
                        content_b64=base64.b64encode(p.read_bytes()).decode("ascii"),
                    )
                )
    return out
