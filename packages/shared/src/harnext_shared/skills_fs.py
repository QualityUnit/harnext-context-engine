"""Skill helpers shared across apps.

apps/ingest uses ``skill_file_meta`` / ``parse_skill_description`` when storing
skills; apps/builder uses ``materialize_skills`` to drop every org skill into an
agent working dir as ``.claude/skills/{name}/`` before a build. Wire-format
compatibility target: ``fastmcp.utilities.skills`` (the ``skill://`` client).
"""

import hashlib
import mimetypes
import re
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harnext_shared.db import Skill, SkillFile

# A skill name doubles as the skill:// URI host and the on-disk directory name.
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_DESCRIPTION_MAX = 200


def skill_file_meta(path: str, content: bytes) -> tuple[str, int, str]:
    """``(mime_type, size, "sha256:<hex>")`` for one skill file.

    The single source of truth for ``SkillFile`` metadata — used by the ingest
    API at write time and by the MCP ``_manifest`` / tests at read time."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in (".md", ".markdown"):
        mime = "text/markdown"  # stdlib mimetypes lacks .md on some platforms
    else:
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return mime, len(content), f"sha256:{hashlib.sha256(content).hexdigest()}"


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter from markdown — mirrors fastmcp's simple
    ``key: value`` parser (``fastmcp/server/providers/skills/_common.py``)."""
    if not content.startswith("---"):
        return {}, content

    end = re.search(r"\n---\s*\n", content[3:])
    if not end:
        return {}, content

    frontmatter_text = content[3 : 3 + end.start()]
    remaining = content[3 + end.end() :]

    frontmatter: dict[str, str] = {}
    for line in frontmatter_text.strip().split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        frontmatter[key] = value
    return frontmatter, remaining


def parse_skill_description(skill_md: str) -> str:
    """Description for a skill from its ``SKILL.md``: the frontmatter
    ``description`` if present, else the first non-heading body line (falling
    back to the first heading's text for heading-only files)."""
    frontmatter, body = _parse_frontmatter(skill_md)
    description = frontmatter.get("description", "").strip()
    if description:
        return description[:_DESCRIPTION_MAX]

    heading = ""
    for raw in body.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not heading:
                heading = line.lstrip("#").strip()[:_DESCRIPTION_MAX]
            continue
        return line[:_DESCRIPTION_MAX]
    return heading


def _is_safe_relpath(path: str) -> bool:
    """Relative POSIX with no traversal: no leading "/", no "..", no "\\"."""
    if not path or path.startswith("/") or "\\" in path:
        return False
    return ".." not in PurePosixPath(path).parts


async def materialize_skills(
    sm: async_sessionmaker[AsyncSession], org_id: str, dest_dir: str | Path
) -> list[Path]:
    """Write every skill of ``org_id`` to ``{dest_dir}/.claude/skills/{name}/``.

    Unsafe rows (bad skill name, absolute / ``..`` / backslash paths, anything
    that resolves outside its skill dir) are skipped, not raised — one bad row
    must never break a build. Returns the skill dirs that received files."""
    skills_root = (Path(dest_dir) / ".claude" / "skills").resolve()

    written: list[Path] = []
    async with sm() as session:
        skills = (
            (await session.execute(select(Skill).where(Skill.org_id == org_id).order_by(Skill.name)))
            .scalars()
            .all()
        )
        for skill in skills:
            if not SKILL_NAME_RE.match(skill.name):
                continue  # defense in depth: the name is also a directory name
            skill_dir = skills_root / skill.name
            files = (
                (
                    await session.execute(
                        select(SkillFile)
                        .where(SkillFile.skill_id == skill.id)
                        .order_by(SkillFile.path)
                    )
                )
                .scalars()
                .all()
            )
            wrote = False
            for f in files:
                if not _is_safe_relpath(f.path):
                    continue
                target = (skill_dir / f.path).resolve()
                if not target.is_relative_to(skill_dir):
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(f.content)
                except OSError:
                    continue  # e.g. a file/dir path collision ("a" + "a/b")
                wrote = True
            if wrote:
                written.append(skill_dir)
    return written
