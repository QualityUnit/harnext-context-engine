"""Polling scheduler: per-source poll-state watermark + the Celery wiring."""

from datetime import timedelta

from harnext_ingest.service import SourceService
from harnext_ingest.settings import IngestSettings
from harnext_shared import (
    SourcePollState,
    init_db,
    make_engine,
    make_sessionmaker,
    utcnow,
)


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, event):
        self.sent.append((topic, event))


async def _svc(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)  # alembic upgrade head — creates source_poll_state
    return SourceService(make_sessionmaker(engine), FakeProducer(), IngestSettings()), engine


async def _make_source(svc):
    u = await svc.register("a@b.com", "hunter2", "A")
    p = await svc.create_project(u.id, "P")
    src = await svc.create_source(p.id, "github", {"repo": "a/b"}, "tok")
    return p, src


async def test_poll_state_created_with_source(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        p, src = await _make_source(svc)
        async with make_sessionmaker(engine)() as s:
            st = await s.get(SourcePollState, src.id)
        assert st is not None
        assert st.org_id == p.id
        assert st.interval_seconds == 3600
        assert st.last_checked_at is not None  # stamped now → first poll one interval out
    finally:
        await engine.dispose()


async def test_claim_due_polls_respects_interval(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        _, src = await _make_source(svc)
        # just created (last_checked_at ≈ now) → not due
        assert await svc.claim_due_polls(now=utcnow()) == []
        # an interval+ later → due exactly once; the claim stamps last_checked_at
        later = utcnow() + timedelta(seconds=3700)
        assert await svc.claim_due_polls(now=later) == [src.id]
        assert await svc.claim_due_polls(now=later) == []  # already claimed
    finally:
        await engine.dispose()


async def test_claim_due_polls_missing_state_is_due(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        _, src = await _make_source(svc)
        # simulate a source created before this feature: no poll-state row
        async with make_sessionmaker(engine)() as s:
            await s.delete(await s.get(SourcePollState, src.id))
            await s.commit()
        # missing state → due immediately, and the claim creates the row
        assert await svc.claim_due_polls(now=utcnow()) == [src.id]
        async with make_sessionmaker(engine)() as s:
            assert await s.get(SourcePollState, src.id) is not None
    finally:
        await engine.dispose()


async def test_paused_source_not_due(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        _, src = await _make_source(svc)
        async with make_sessionmaker(engine)() as s:
            row = await s.get(SourcePollState, src.id)
            row.last_checked_at = None  # would be due…
            src_row = await s.get(type(src), src.id)
            src_row.status = "paused"  # …but it's paused
            await s.commit()
        assert await svc.claim_due_polls(now=utcnow()) == []  # only active sources poll
    finally:
        await engine.dispose()


async def test_poll_state_deleted_with_source(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        _, src = await _make_source(svc)
        assert await svc.delete_source(src.id) is True
        async with make_sessionmaker(engine)() as s:
            assert await s.get(SourcePollState, src.id) is None
    finally:
        await engine.dispose()


async def test_poll_state_deleted_with_project(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        p, src = await _make_source(svc)
        assert await svc.delete_project(p.id) is True
        async with make_sessionmaker(engine)() as s:
            assert await s.get(SourcePollState, src.id) is None
    finally:
        await engine.dispose()


def test_celery_app_and_tasks_registered():
    import harnext_ingest.tasks  # noqa: F401  — registers the tasks
    from harnext_ingest.celery_app import app

    sched = app.conf.beat_schedule
    assert "dispatch-due-polls" in sched
    assert sched["dispatch-due-polls"]["schedule"] == 60.0
    assert "harnext_ingest.tasks.dispatch_due_polls" in app.tasks
    assert "harnext_ingest.tasks.poll_source" in app.tasks
