"""Skills over MCP: the org-scoped skill:// resource surface.

Wire-format compliance is checked with fastmcp's OWN client utilities
(fastmcp.utilities.skills) — the same code real consumers run. The in-memory
client transport bypasses HTTP bearer auth, so the request's org is injected by
patching harnext_mcp.skills.get_access_token — the exact seam the provider
reads — which also lets the tests exercise tenancy (org A vs org B vs no token).
"""

import base64
import uuid
from pathlib import Path

import harnext_mcp.context as mcp_context
import harnext_mcp.skills as mcp_skills
import pytest
from fastmcp import Client
from fastmcp.server.auth import AccessToken
from fastmcp.utilities.skills import (
    download_skill,
    get_skill_manifest,
    list_skills,
    sync_skills,
)
from harnext_builder.agentfs.backend import get_backend
from harnext_builder.agentfs.store import OrgFsStore
from harnext_builder.build_runner import BuildRunner, BuildStatus
from harnext_builder.harness.base import ConversationTranscript, TranscriptTurn
from harnext_builder.persistence import Persistence
from harnext_builder.settings import BuilderSettings
from harnext_mcp.context import Resources
from harnext_mcp.main import mcp
from harnext_mcp.research import research
from harnext_shared import (
    Project,
    Skill,
    SkillFile,
    User,
    init_db,
    make_engine,
    make_sessionmaker,
    skill_file_meta,
)
from mcp.shared.exceptions import McpError

PDF_SKILL_MD = (
    b"---\n"
    b"description: Render branded PDF reports\n"
    b"---\n"
    b"\n"
    b"# pdf-report\n"
    b"\n"
    b"Run scripts/run.py over the data export.\n"
)
RUN_PY = b"print('render pdf')\n"
LOGO_PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(8))  # not utf-8 -> must travel as blob
NOTES_SKILL_MD = b"# notes\n\nKeep org notes tidy.\n"
SECRET_SKILL_MD = b"# secret\n\nOrg B internal playbook.\n"

PDF_FILES = {"SKILL.md": PDF_SKILL_MD, "scripts/run.py": RUN_PY, "assets/logo.png": LOGO_PNG}


async def _setup(tmp_path):
    """Mirror test_mcp._setup, but bundled as the Resources the server uses."""
    settings = BuilderSettings(
        harness="fake",
        agentfs_backend="git",
        agentfs_dir=str(tmp_path / "fs"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/m.sqlite",
        builder_timeout_s=60,
    )
    engine = make_engine(settings.database_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)
    store = OrgFsStore(get_backend(settings), sm)
    res = Resources(
        builder_settings=settings,
        sm=sm,
        store=store,
        build_runner=BuildRunner(store, Persistence(sm), settings),
    )
    return res, engine


async def _seed_org(sm, name: str) -> str:
    async with sm() as s:
        user = User(id=uuid.uuid4().hex, email=f"{name}@example.com")
        s.add(user)
        await s.flush()
        project = Project(id=uuid.uuid4().hex, name=name, owner_id=user.id)
        s.add(project)
        await s.commit()
        return project.id


async def _seed_skill(
    sm, org_id: str, name: str, description: str, files: dict[str, bytes]
) -> str:
    async with sm() as s:
        skill = Skill(id=uuid.uuid4().hex, org_id=org_id, name=name, description=description)
        s.add(skill)
        await s.flush()
        for path, content in files.items():
            mime_type, size, file_hash = skill_file_meta(path, content)
            s.add(
                SkillFile(
                    id=uuid.uuid4().hex, skill_id=skill.id, path=path,
                    mime_type=mime_type, size=size, hash=file_hash, content=content,
                )
            )
        await s.commit()
        return skill.id


def _as_org(monkeypatch, org_id: str | None) -> None:
    """The in-memory transport carries no bearer token; inject the verified-token
    outcome at the seam the provider resolves it from."""
    token = (
        None
        if org_id is None
        else AccessToken(token="test-token", client_id=org_id, scopes=["mcp"])
    )
    monkeypatch.setattr(mcp_skills, "get_access_token", lambda: token)


async def test_skills_wire_format_and_tenancy(tmp_path, monkeypatch):
    res, engine = await _setup(tmp_path)
    monkeypatch.setattr(mcp_context, "_res", res)
    try:
        org_a = await _seed_org(res.sm, "acme")
        org_b = await _seed_org(res.sm, "globex")
        await _seed_skill(res.sm, org_a, "pdf-report", "Render branded PDF reports", PDF_FILES)
        await _seed_skill(res.sm, org_a, "notes", "Keep org notes tidy.", {"SKILL.md": NOTES_SKILL_MD})
        await _seed_skill(res.sm, org_b, "secret", "Org B internal playbook.", {"SKILL.md": SECRET_SKILL_MD})

        _as_org(monkeypatch, org_a)
        async with Client(mcp) as client:
            # list_skills: exactly org A's two skills, with their descriptions.
            skills = await list_skills(client)
            assert {(s.name, s.description, s.uri) for s in skills} == {
                ("notes", "Keep org notes tidy.", "skill://notes/SKILL.md"),
                ("pdf-report", "Render branded PDF reports", "skill://pdf-report/SKILL.md"),
            }

            # get_skill_manifest: ALL files incl. SKILL.md, exact sizes + sha256.
            manifest = await get_skill_manifest(client, "pdf-report")
            assert manifest.name == "pdf-report"
            assert {(f.path, f.size, f.hash) for f in manifest.files} == {
                (path, *skill_file_meta(path, content)[1:])
                for path, content in PDF_FILES.items()
            }

            # download_skill: the full tree round-trips byte-for-byte
            # (markdown + python as text, the png through the blob path).
            skill_dir = await download_skill(client, "pdf-report", tmp_path / "dl")
            assert skill_dir.name == "pdf-report"
            for path, content in PDF_FILES.items():
                assert (skill_dir / path).read_bytes() == content

            # sync_skills: downloads every org-A skill.
            synced = await sync_skills(client, tmp_path / "sync")
            assert sorted(p.name for p in synced) == ["notes", "pdf-report"]
            assert (tmp_path / "sync" / "notes" / "SKILL.md").read_bytes() == NOTES_SKILL_MD

            # Tenancy: org A must not read org B's skill, even by direct URI.
            with pytest.raises(McpError):
                await client.read_resource("skill://secret/SKILL.md")
            with pytest.raises(McpError):
                await client.read_resource("skill://secret/_manifest")

            # Unknown path within an owned skill resolves to nothing too.
            with pytest.raises(McpError):
                await client.read_resource("skill://pdf-report/nope.txt")
    finally:
        await engine.dispose()


async def test_skill_paths_needing_uri_encoding_round_trip(tmp_path, monkeypatch):
    """Paths with spaces/non-ASCII are percent-encoded in the listed skill://
    URIs; the provider must resolve both the encoded form (what it listed) and
    serve the bytes intact through download_skill/sync_skills."""
    res, engine = await _setup(tmp_path)
    monkeypatch.setattr(mcp_context, "_res", res)
    try:
        org = await _seed_org(res.sm, "acme")
        files = {
            "SKILL.md": b"# spacey\n\nFiles with awkward names.\n",
            "my file.txt": b"space in the name\n",
            "docs/résumé.md": b"# non-ascii path\n",
        }
        await _seed_skill(res.sm, org, "spacey", "Awkward names.", files)

        _as_org(monkeypatch, org)
        async with Client(mcp) as client:
            # the server resolves the exact (encoded) URI it listed
            listed = {str(r.uri) for r in await client.list_resources()}
            assert "skill://spacey/my%20file.txt" in listed
            blocks = await client.read_resource("skill://spacey/my%20file.txt")
            assert blocks[0].text == "space in the name\n"

            # the full client flow survives: manifest paths are raw, fetchable
            manifest = await get_skill_manifest(client, "spacey")
            assert {f.path for f in manifest.files} == set(files)
            skill_dir = await download_skill(client, "spacey", tmp_path / "dl")
            for path, content in files.items():
                assert (skill_dir / path).read_bytes() == content
            synced = await sync_skills(client, tmp_path / "sync")
            assert [p.name for p in synced] == ["spacey"]
    finally:
        await engine.dispose()


async def test_text_mime_with_non_utf8_bytes_served_as_blob(tmp_path, monkeypatch):
    """A text/*-mime file whose bytes aren't valid UTF-8 (mime is guessed from
    the extension) must fall back to the blob path instead of erroring — one
    such file must not abort download_skill/sync_skills for the org."""
    res, engine = await _setup(tmp_path)
    monkeypatch.setattr(mcp_context, "_res", res)
    try:
        org = await _seed_org(res.sm, "acme")
        latin1 = "caf\xe9 notes\n".encode("latin-1")  # not valid utf-8
        await _seed_skill(
            res.sm, org, "badtext", "Mislabeled bytes.",
            {"SKILL.md": NOTES_SKILL_MD, "notes.txt": latin1},
        )

        _as_org(monkeypatch, org)
        async with Client(mcp) as client:
            blocks = await client.read_resource("skill://badtext/notes.txt")
            assert base64.b64decode(blocks[0].blob) == latin1  # blob, byte-exact

            skill_dir = await download_skill(client, "badtext", tmp_path / "dl")
            assert (skill_dir / "notes.txt").read_bytes() == latin1
            synced = await sync_skills(client, tmp_path / "sync")
            assert [p.name for p in synced] == ["badtext"]
    finally:
        await engine.dispose()


async def test_skills_invisible_without_token(tmp_path, monkeypatch):
    """No/invalid bearer token: nothing listed, nothing readable — never leak."""
    res, engine = await _setup(tmp_path)
    monkeypatch.setattr(mcp_context, "_res", res)
    try:
        org_a = await _seed_org(res.sm, "acme")
        await _seed_skill(res.sm, org_a, "notes", "Keep org notes tidy.", {"SKILL.md": NOTES_SKILL_MD})

        _as_org(monkeypatch, None)
        async with Client(mcp) as client:
            assert await list_skills(client) == []
            with pytest.raises(McpError):
                await client.read_resource("skill://notes/SKILL.md")
    finally:
        await engine.dispose()


async def test_research_working_dir_gets_org_skills(tmp_path, monkeypatch):
    """research() materializes the org's skills as .claude/skills/ next to the
    snapshot files in the agent's working dir."""
    res, engine = await _setup(tmp_path)
    try:
        org = await _seed_org(res.sm, "acme")
        await _seed_skill(
            res.sm, org, "pdf-report", "Render branded PDF reports",
            {"SKILL.md": PDF_SKILL_MD, "scripts/run.py": RUN_PY},
        )
        out = await res.build_runner.run_update(org, "Note: hello.", uuid.uuid4().hex)
        assert out.status is BuildStatus.SUCCESS

        seen: dict[str, list[str]] = {}

        def _tree(root: str) -> list[str]:
            wd = Path(root)
            return sorted(
                p.relative_to(wd).as_posix() for p in wd.rglob("*") if p.is_file()
            )

        class SpyHarness:
            name = "spy"

            async def run(self, req):
                seen["files"] = _tree(req.working_dir)
                return ConversationTranscript(
                    harness="spy",
                    turns=[TranscriptTurn(role="assistant", content="ok")],
                )

        monkeypatch.setattr("harnext_mcp.research.get_harness", lambda _name: SpyHarness())
        result = await research(res.store, res.builder_settings, org, "what skills exist?")
        assert result["answer"] == "ok"
        assert ".claude/skills/pdf-report/SKILL.md" in seen["files"]
        assert ".claude/skills/pdf-report/scripts/run.py" in seen["files"]
        assert "INDEX.md" in seen["files"]  # the snapshot is still there too
    finally:
        await engine.dispose()
