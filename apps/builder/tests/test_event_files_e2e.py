"""E2E: a GitHub commit event carrying changed files flows through the real
runner subprocess → the agent reads them from `_event/` → the durable FS records
what it saw, and `_event/` itself is never snapshotted or counted as a change.

Parametrized over both backends (git always; agentfs when the binary is present),
so the agentfs `exec` mount path is exercised too.
"""

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from meaninggrid_builder.agentfs.backend import get_backend
from meaninggrid_builder.agentfs.store import OrgFsStore
from meaninggrid_builder.build_runner import BuildRunner, BuildStatus
from meaninggrid_builder.event_fs import EVENT_DIR
from meaninggrid_builder.persistence import Persistence
from meaninggrid_builder.settings import BuilderSettings
from meaninggrid_builder.work_item import WorkItem
from meaninggrid_shared import CloudEvent, ConversationLog, init_db, make_engine, make_sessionmaker
from sqlalchemy import select


def _agentfs_available() -> bool:
    from meaninggrid_builder.agentfs.agentfs_backend import resolve_agentfs_bin

    b = resolve_agentfs_bin("agentfs")
    if not (shutil.which(b) or Path(b).exists()):
        return False
    try:
        subprocess.run([b, "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


BACKENDS = ["git"] + (["agentfs"] if _agentfs_available() else [])

MARKER = "CHANGED-FILE-BODY-12345"


def _commit_with_files() -> CloudEvent:
    return CloudEvent(
        id="github-commit-acme/web-abc",
        source="github:acme/web",
        type="com.github.commit",
        subject="repo:acme/web",
        time=datetime.now(UTC),
        mgtenant="acme",
        data={
            "sha": "abc",
            "message": "touch app",
            "author": "ada",
            "files": [
                {"path": "src/app.py", "status": "modified", "content": f"# {MARKER}\n"},
                {"path": "deleted.txt", "status": "removed"},
            ],
        },
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


@pytest.mark.parametrize("backend", BACKENDS)
async def test_agent_reads_event_files_and_they_are_not_snapshotted(tmp_path, backend):
    runner, store, sm, engine = await _runner(tmp_path, backend)
    try:
        wi = WorkItem.from_fast_event(_commit_with_files())
        out = await runner.run(wi)
        assert out.status is BuildStatus.SUCCESS, out.error

        # 1. the agent could read the changed file from _event/ (proof folded in)
        marker = await store.read_file("acme", "_meta/last_build.md")
        assert marker is not None and MARKER in marker

        # 2. _event/ is reference-only: nothing from it is in the snapshot
        files = await store.list_files("acme")
        assert not any(EVENT_DIR in f.split("/") for f in files)

        # 3. and it never shows up as a file the build "changed"
        async with sm() as s:
            log = (await s.execute(select(ConversationLog))).scalars().first()
            assert log is not None
            changed = json.loads(log.files_changed_json)
            assert not any(EVENT_DIR in fc for fc in changed)
    finally:
        await engine.dispose()
