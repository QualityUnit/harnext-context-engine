"""Project-scoped skills served over MCP as ``skill://`` resources.

DB-backed twin of fastmcp's filesystem ``SkillProvider``
(``fastmcp/server/providers/skills/skill_provider.py``), byte-compatible with
the ``fastmcp.utilities.skills`` client utilities:

  - ``skill://{name}/SKILL.md``   — one listed resource per skill; its
    ``description`` is the skill's description (what ``list_skills`` shows).
  - ``skill://{name}/_manifest``  — JSON ``{"skill", "files": [{path, size,
    hash}]}`` over ALL files including ``SKILL.md`` (``download_skill``
    re-fetches every file by path from this list).
  - ``skill://{name}/{path}``     — every file readable at its URI; text mimes
    as text, everything else as bytes (blob).

Supporting files are enumerated up front (the provider's "resources" mode), so
no resource templates are exposed. Every method resolves the tenant from the
request's verified bearer token — no/invalid token lists nothing and resolves
no URI, and one org can never read another org's skills even by guessing URIs.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import PurePosixPath
from urllib.parse import unquote

from fastmcp.resources.base import Resource
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.providers.base import Provider
from fastmcp.utilities.versions import VersionSpec
from harnext_shared import Skill, SkillFile
from harnext_shared.skills_fs import SKILL_NAME_RE
from pydantic import AnyUrl
from sqlalchemy import select

from harnext_mcp.context import get_resources

_MAIN_FILE = "SKILL.md"
_MANIFEST = "_manifest"


def _request_org() -> str | None:
    """The tenant for the current request, or None — unlike the tools' _org(),
    providers must stay silent (list nothing, resolve nothing), not error."""
    token = get_access_token()
    if token is None or not token.client_id:
        return None
    return token.client_id


def _is_safe_relpath(path: str) -> bool:
    """Relative POSIX, no traversal, and not the synthetic manifest name."""
    if not path or path.startswith("/") or "\\" in path or path == _MANIFEST:
        return False
    return ".." not in PurePosixPath(path).parts


def _is_text_mime(mime_type: str) -> bool:
    # Mirrors fastmcp's SkillProvider: text/* is served as text, rest as blob.
    return mime_type.startswith("text/")


class SkillDbFileResource(Resource):
    """One skill file, read from the DB on demand (content is never preloaded
    so listings stay metadata-only)."""

    skill_id: str
    skill_name: str
    file_path: str

    async def read(self) -> str | bytes:
        res = await get_resources()
        async with res.sm() as session:
            row = (
                await session.execute(
                    select(SkillFile).where(
                        SkillFile.skill_id == self.skill_id,
                        SkillFile.path == self.file_path,
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            raise FileNotFoundError(f"File not found: {self.file_path}")
        if _is_text_mime(row.mime_type):
            try:
                return row.content.decode("utf-8")
            except UnicodeDecodeError:
                pass  # mislabeled binary — serve as blob; b64 keeps byte fidelity
        return row.content


class SkillDbManifestResource(Resource):
    """The synthetic ``_manifest``: every file of the skill (incl. SKILL.md)
    with the stored size + sha256, generated from the DB metadata columns."""

    skill_id: str
    skill_name: str

    async def read(self) -> str:
        res = await get_resources()
        async with res.sm() as session:
            rows = (
                await session.execute(
                    select(SkillFile.path, SkillFile.size, SkillFile.hash)
                    .where(SkillFile.skill_id == self.skill_id)
                    .order_by(SkillFile.path)
                )
            ).all()
        manifest = {
            "skill": self.skill_name,
            "files": [
                {"path": path, "size": size, "hash": file_hash}
                for path, size, file_hash in rows
                if _is_safe_relpath(path)
            ],
        }
        return json.dumps(manifest, indent=2)


class SkillsProvider(Provider):
    """Serves the request org's skills (DB rows) as ``skill://`` resources."""

    async def _list_resources(self) -> Sequence[Resource]:
        org = _request_org()
        if org is None:
            return []
        res = await get_resources()
        out: list[Resource] = []
        async with res.sm() as session:
            skills = (
                (
                    await session.execute(
                        select(Skill).where(Skill.org_id == org).order_by(Skill.name)
                    )
                )
                .scalars()
                .all()
            )
            for skill in skills:
                if not SKILL_NAME_RE.match(skill.name):
                    continue  # the name is a URI host + directory name
                rows = (
                    await session.execute(
                        select(SkillFile.path, SkillFile.mime_type)
                        .where(SkillFile.skill_id == skill.id)
                        .order_by(SkillFile.path)
                    )
                ).all()  # metadata only — never pull content blobs for a listing
                paths = {path for path, _ in rows}
                if _MAIN_FILE not in paths:
                    continue  # ingest guarantees SKILL.md; skip malformed rows

                out.append(
                    SkillDbFileResource(
                        uri=AnyUrl(f"skill://{skill.name}/{_MAIN_FILE}"),
                        name=f"{skill.name}/{_MAIN_FILE}",
                        description=skill.description,
                        mime_type="text/markdown",
                        skill_id=skill.id,
                        skill_name=skill.name,
                        file_path=_MAIN_FILE,
                    )
                )
                out.append(
                    SkillDbManifestResource(
                        uri=AnyUrl(f"skill://{skill.name}/{_MANIFEST}"),
                        name=f"{skill.name}/{_MANIFEST}",
                        description=f"File listing for {skill.name}",
                        mime_type="application/json",
                        skill_id=skill.id,
                        skill_name=skill.name,
                    )
                )
                for path, mime_type in rows:
                    if path == _MAIN_FILE or not _is_safe_relpath(path):
                        continue
                    out.append(
                        SkillDbFileResource(
                            uri=AnyUrl(f"skill://{skill.name}/{path}"),
                            name=f"{skill.name}/{path}",
                            description=f"File from {skill.name} skill",
                            mime_type=mime_type or "application/octet-stream",
                            skill_id=skill.id,
                            skill_name=skill.name,
                            file_path=path,
                        )
                    )
        return out

    async def _get_resource(
        self, uri: str, version: VersionSpec | None = None
    ) -> Resource | None:
        org = _request_org()
        if org is None:
            return None

        # Parse skill://{name}/{path}. Clients normalize URIs through AnyUrl,
        # so paths with spaces/non-ASCII arrive percent-encoded — decode them
        # back to the stored form ('#', '?' and '%' are rejected at ingest, so
        # unquoting is unambiguous).
        if not uri.startswith("skill://"):
            return None
        parts = uri[len("skill://") :].split("/", 1)
        if len(parts) != 2 or not parts[1]:
            return None
        skill_name, file_path = unquote(parts[0]), unquote(parts[1])
        if not SKILL_NAME_RE.match(skill_name):
            return None

        res = await get_resources()
        async with res.sm() as session:
            skill = (
                await session.execute(
                    select(Skill).where(Skill.org_id == org, Skill.name == skill_name)
                )
            ).scalar_one_or_none()
            if skill is None:
                return None  # unknown to this org — never confirm other tenants

            if file_path == _MANIFEST:
                return SkillDbManifestResource(
                    uri=AnyUrl(uri),
                    name=f"{skill_name}/{_MANIFEST}",
                    description=f"File listing for {skill_name}",
                    mime_type="application/json",
                    skill_id=skill.id,
                    skill_name=skill_name,
                )

            if not _is_safe_relpath(file_path):
                return None
            mime_type = (
                await session.execute(
                    select(SkillFile.mime_type).where(
                        SkillFile.skill_id == skill.id, SkillFile.path == file_path
                    )
                )
            ).scalar_one_or_none()
            if mime_type is None:
                return None

        return SkillDbFileResource(
            uri=AnyUrl(uri),
            name=f"{skill_name}/{file_path}",
            description=(
                skill.description
                if file_path == _MAIN_FILE
                else f"File from {skill_name} skill"
            ),
            mime_type=mime_type or "application/octet-stream",
            skill_id=skill.id,
            skill_name=skill_name,
            file_path=file_path,
        )
