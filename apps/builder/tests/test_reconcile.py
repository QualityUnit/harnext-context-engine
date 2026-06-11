"""Startup reconciliation: discard partial edits, fail orphaned running builds."""

import uuid
from pathlib import Path

from harnext_builder.agentfs.backend import get_backend
from harnext_builder.agentfs.store import OrgFsStore
from harnext_builder.build_runner import BuildRunner
from harnext_builder.persistence import Persistence
from harnext_builder.reconcile import reconcile
from harnext_builder.settings import BuilderSettings
from harnext_shared import BuildLedger, init_db, make_engine, make_sessionmaker


async def test_reconcile_rolls_back_and_fails_orphans(tmp_path):
    settings = BuilderSettings(
        harness="fake",
        agentfs_backend="git",
        agentfs_dir=str(tmp_path / "fs"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/m.sqlite",
    )
    engine = make_engine(settings.database_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)
    store = OrgFsStore(get_backend(settings), sm)
    br = BuildRunner(store, Persistence(sm), settings)
    try:
        await br.run_update("acme", "note", uuid.uuid4().hex)  # genesis + a build snapshot

        # simulate a crash: a stray partial edit in the live FS + a running ledger row
        (Path(settings.agentfs_dir) / "git" / "acme" / "STRAY.md").write_text("partial")
        async with sm() as s:
            s.add(
                BuildLedger(
                    org_id="acme",
                    dedupe_key="orphan",
                    build_id="x",
                    lane="fast",
                    status="running",
                )
            )
            await s.commit()

        await reconcile(store, sm)

        assert await store.read_file("acme", "STRAY.md") is None  # partial edit discarded
        async with sm() as s:
            row = await s.get(BuildLedger, ("acme", "orphan"))
            assert row is not None and row.status == "failed"
    finally:
        await engine.dispose()
