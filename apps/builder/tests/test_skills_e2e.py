"""E2E: project Skills stored in the metadata DB are mounted at
``.claude/skills/`` in the agent's working dir for the build, and — like
``_event/`` — never written back into the org context store (not in the
snapshot, not in the live FS, not in ``files_changed``).

Parametrized over both backends (git always; agentfs when the binary is present),
so the agentfs ``exec`` mount path is exercised too.
"""

import base64
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from harnext_builder.agentfs.backend import get_backend
from harnext_builder.agentfs.store import OrgFsStore
from harnext_builder.build_runner import BuildRunner, BuildStatus
from harnext_builder.harness.base import SkillMountFile
from harnext_builder.harness.runner import _materialize_skills
from harnext_builder.persistence import Persistence
from harnext_builder.settings import BuilderSettings
from harnext_builder.skills_mount import skill_mount_files
from harnext_builder.work_item import WorkItem
from harnext_shared import (
    CloudEvent,
    ConversationLog,
    Project,
    Skill,
    SkillFile,
    User,
    init_db,
    make_engine,
    make_sessionmaker,
    skill_file_meta,
)
from sqlalchemy import select


def _agentfs_available() -> bool:
    from harnext_builder.agentfs.agentfs_backend import resolve_agentfs_bin

    b = resolve_agentfs_bin("agentfs")
    if not (shutil.which(b) or Path(b).exists()):
        return False
    try:
        subprocess.run([b, "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


BACKENDS = ["git"] + (["agentfs"] if _agentfs_available() else [])

MARKER = "SKILL-BODY-67890"

SKILL_FILES = {
    "SKILL.md": f"---\ndescription: How we do research\n---\n\n# Research\n\n{MARKER}\n".encode(),
    "scripts/helper.py": b"print('research helper')\n",
}


def _event(eid: str, org: str = "acme") -> CloudEvent:
    return CloudEvent(
        id=eid,
        source="github:acme/web",
        type="com.github.push",
        subject="repo:acme/web",
        time=datetime.now(UTC),
        mgtenant=org,
        data={"message": f"event {eid}"},
    )


async def _runner(tmp_path, backend):
    settings = BuilderSettings(
        harness="fake",
        agentfs_backend=backend,
        agentfs_dir=str(tmp_path / "fs"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite",
        builder_timeout_s=60,
    )
    engine = make_engine(settings.database_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)
    store = OrgFsStore(get_backend(settings), sm)
    return BuildRunner(store, Persistence(sm), settings), store, sm, engine


async def _seed_skill(sm, org_id: str, name: str = "research", files: dict | None = None) -> None:
    """Insert a project + skill the way the ingest API would (FKs are enforced,
    and with no ORM relationships parents must be flushed before children)."""
    async with sm() as s:
        user = User(id=uuid4().hex, email=f"{uuid4().hex}@example.com")
        s.add(user)
        await s.flush()
        s.add(Project(id=org_id, name="P", owner_id=user.id))
        await s.flush()
        skill = Skill(id=uuid4().hex, org_id=org_id, name=name, description="d")
        s.add(skill)
        await s.flush()
        for path, content in (files or SKILL_FILES).items():
            mime, size, digest = skill_file_meta(path, content)
            s.add(
                SkillFile(
                    id=uuid4().hex,
                    skill_id=skill.id,
                    path=path,
                    mime_type=mime,
                    size=size,
                    hash=digest,
                    content=content,
                )
            )
        await s.commit()


@pytest.mark.parametrize("backend", BACKENDS)
async def test_skills_mounted_for_harness_and_never_written_back(tmp_path, backend):
    runner, store, sm, engine = await _runner(tmp_path, backend)
    try:
        await _seed_skill(sm, "acme")
        out = await runner.run(WorkItem.from_fast_event(_event("e1")))
        assert out.status is BuildStatus.SUCCESS, out.error

        # 1. the agent saw the mounted skill during the build (proof folded in)
        marker = await store.read_file("acme", "_meta/last_build.md")
        assert marker is not None
        assert ".claude/skills/research/SKILL.md" in marker and MARKER in marker
        assert ".claude/skills/research/scripts/helper.py" in marker

        # 2. the mount is reference-only: nothing under .claude/ reaches the
        # live FS or the committed snapshot
        for files in (
            await store.list_files("acme"),
            await store.list_files("acme", snapshot_id=out.snapshot_id),
        ):
            assert files  # sanity: the listing itself works
            assert not [f for f in files if ".claude" in f.split("/")]

        # 3. and it never shows up as a file the build "changed"
        async with sm() as s:
            log = (await s.execute(select(ConversationLog))).scalars().one()
            changed = json.loads(log.files_changed_json)
            assert not [fc for fc in changed if ".claude" in fc]
    finally:
        await engine.dispose()


@pytest.mark.parametrize("backend", BACKENDS)
async def test_org_without_skills_builds_with_no_mount(tmp_path, backend):
    runner, store, sm, engine = await _runner(tmp_path, backend)
    try:
        out = await runner.run(WorkItem.from_fast_event(_event("e1")))
        assert out.status is BuildStatus.SUCCESS, out.error

        marker = await store.read_file("acme", "_meta/last_build.md")
        assert marker is not None and ".claude/skills" not in marker
        assert not [f for f in await store.list_files("acme") if ".claude" in f.split("/")]
    finally:
        await engine.dispose()


async def test_skill_mount_files_packs_org_skills_base64(tmp_path):
    """Binary-safe round trip + org scoping for the request payload."""
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    sm = make_sessionmaker(engine)
    try:
        binary = b"\x89PNG\r\n\x00not-utf8\xff"
        await _seed_skill(sm, "acme", files={"SKILL.md": b"# S\n\nDo it.\n", "assets/logo.bin": binary})

        files = await skill_mount_files(sm, "acme")
        by_path = {f.path: base64.b64decode(f.content_b64) for f in files}
        assert by_path == {
            ".claude/skills/research/SKILL.md": b"# S\n\nDo it.\n",
            ".claude/skills/research/assets/logo.bin": binary,
        }

        # another org sees nothing
        assert await skill_mount_files(sm, "other-org") == []
    finally:
        await engine.dispose()


def test_runner_skill_mount_guards_against_escapes(tmp_path):
    """The runner only writes under .claude/skills/ — defense in depth on top of
    materialize_skills' own path checks."""

    def b64(b: bytes) -> str:
        return base64.b64encode(b).decode("ascii")

    _materialize_skills(
        tmp_path,
        [
            SkillMountFile(path=".claude/skills/ok/SKILL.md", content_b64=b64(b"# ok\n")),
            SkillMountFile(path="evil.txt", content_b64=b64(b"x")),  # outside the mount
            SkillMountFile(path=".claude/skills", content_b64=b64(b"x")),  # the mount itself
            SkillMountFile(path=".claude/skills/../settings.json", content_b64=b64(b"x")),
            SkillMountFile(path=".claude/skills/../../../escape.txt", content_b64=b64(b"x")),
        ],
    )
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert written == [".claude/skills/ok/SKILL.md"]
