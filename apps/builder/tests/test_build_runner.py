"""End-to-end builder (no Kafka): WorkItem → BuildRunner → FS + ledger + log.

Parametrized over both backends; the agentfs case also exercises env
propagation + host-path access through ``agentfs exec``.
"""

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from harnext_builder.agentfs.backend import get_backend
from harnext_builder.agentfs.store import OrgFsStore
from harnext_builder.build_runner import BuildRunner, BuildStatus
from harnext_builder.persistence import Persistence
from harnext_builder.settings import BuilderSettings
from harnext_builder.work_item import WorkItem
from harnext_shared import (
    BuildLedger,
    CloudEvent,
    ConversationLog,
    init_db,
    make_engine,
    make_sessionmaker,
)
from sqlalchemy import func, select


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


async def _runner(tmp_path, backend: str, harness: str = "fake"):
    settings = BuilderSettings(
        harness=harness,
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
async def test_success_and_idempotency(tmp_path, backend):
    runner, store, sm, engine = await _runner(tmp_path, backend)
    try:
        wi = WorkItem.from_fast_event(_event("e1"))

        out = await runner.run(wi)
        assert out.status is BuildStatus.SUCCESS, out.error
        assert out.snapshot_id and out.conversation_id

        # the fake harness wrote a marker into the FS, captured in the snapshot
        assert await store.read_file("acme", "_meta/last_build.md") is not None
        latest = await store.latest_snapshot("acme")
        assert latest is not None and latest.kind == "build" and latest.id == out.snapshot_id

        async with sm() as s:
            led = await s.get(BuildLedger, ("acme", wi.dedupe_key))
            assert led is not None and led.status == "success"
            n_conv = await s.scalar(select(func.count()).select_from(ConversationLog))
            assert n_conv == 1

        # redelivery short-circuits
        again = await runner.run(wi)
        assert again.status is BuildStatus.SKIPPED
    finally:
        await engine.dispose()


@pytest.mark.parametrize("backend", BACKENDS)
async def test_failure_rolls_back(tmp_path, backend):
    # harness=codex → the runner raises NotImplementedError → no result → FAILED
    runner, store, sm, engine = await _runner(tmp_path, backend, harness="codex")
    try:
        wi = WorkItem.from_fast_event(_event("bad"))
        out = await runner.run(wi)
        assert out.status is BuildStatus.FAILED
        assert out.error

        # rolled back to genesis: no build marker, latest snapshot is genesis
        assert await store.read_file("acme", "_meta/last_build.md") is None
        latest = await store.latest_snapshot("acme")
        assert latest is not None and latest.kind == "genesis"

        async with sm() as s:
            led = await s.get(BuildLedger, ("acme", wi.dedupe_key))
            assert led is not None and led.status == "failed"
    finally:
        await engine.dispose()
