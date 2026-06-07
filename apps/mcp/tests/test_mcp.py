"""MCP tool internals: context_update (write path), research, get_urls.

Uses the fake harness + git backend, so no Anthropic key is needed.
"""

import uuid

from meaninggrid_builder.agentfs.backend import get_backend
from meaninggrid_builder.agentfs.store import OrgFsStore
from meaninggrid_builder.build_runner import BuildRunner, BuildStatus
from meaninggrid_builder.persistence import Persistence
from meaninggrid_builder.settings import BuilderSettings
from meaninggrid_mcp.conversation import conversation_url, get_conversation_payload
from meaninggrid_mcp.research import research
from meaninggrid_shared import init_db, make_engine, make_sessionmaker


async def _setup(tmp_path):
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
    return settings, sm, store, BuildRunner(store, Persistence(sm), settings), engine


async def test_update_research_and_geturls(tmp_path):
    settings, sm, store, br, engine = await _setup(tmp_path)
    try:
        out = await br.run_update("acme", "Note: the auth module was refactored.", uuid.uuid4().hex)
        assert out.status is BuildStatus.SUCCESS and out.conversation_id

        res = await research(store, settings, "acme", "what changed?")
        assert res["snapshot_id"] is not None
        assert res["answer"]
        assert "CLAUDE.md" in res["files"]

        payload = await get_conversation_payload(sm, "acme", conversation_url(out.conversation_id))
        assert payload["found"] is True
        assert "auth module" in payload["instruction"]

        miss = await get_conversation_payload(sm, "acme", "cms://conversation/nope")
        assert miss["found"] is False
        cross = await get_conversation_payload(sm, "other", conversation_url(out.conversation_id))
        assert cross["found"] is False
    finally:
        await engine.dispose()


async def test_research_no_context(tmp_path):
    settings, sm, store, _br, engine = await _setup(tmp_path)
    try:
        res = await research(store, settings, "ghost-org", "anything")
        assert res["snapshot_id"] is None
        assert "No context" in res["answer"]
    finally:
        await engine.dispose()
