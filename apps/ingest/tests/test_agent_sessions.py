"""Pushed agent conversations: open/append/finalize + tenant isolation."""

from meaninggrid_ingest.main import _maybe_json
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings
from meaninggrid_shared import init_db, make_engine, make_sessionmaker


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, event):
        self.sent.append((topic, event))


async def _svc(tmp_path, **overrides):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    settings = IngestSettings(**overrides)
    return SourceService(make_sessionmaker(engine), FakeProducer(), settings), engine


def _ev(seq, type_="assistant", payload=None):
    return {"seq": seq, "type": type_, "payload": payload or {"text": f"turn {seq}"}}


async def test_open_is_idempotent(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        a = await svc.open_agent_session("org-1", "cs-abc", "harnext", "opus", "/tmp", "hello")
        b = await svc.open_agent_session("org-1", "cs-abc", "harnext", "opus", "/tmp", "hello")
        assert a.id == b.id  # same client_session_id → same row
        # a different client session is a different row
        c = await svc.open_agent_session("org-1", "cs-xyz", "harnext", None, None, None)
        assert c.id != a.id
    finally:
        await engine.dispose()


async def test_append_ordering_and_idempotency(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        sess = await svc.open_agent_session("org-1", "cs-1", "harnext", None, None, None)
        r1 = await svc.append_agent_events(sess.id, "org-1", [_ev(0), _ev(1)])
        assert r1 == {"accepted": 2, "duplicates": 0, "max_seq": 1}
        # re-send seq 1 + new seq 2 → only 2 is accepted
        r2 = await svc.append_agent_events(sess.id, "org-1", [_ev(1), _ev(2)])
        assert r2["accepted"] == 1 and r2["duplicates"] == 1

        events = await svc.get_agent_session_events(sess.id)
        assert [e.seq for e in events] == [0, 1, 2]  # ordered by seq
        reread = await svc.get_agent_session(sess.id)
        assert reread.event_count == 3
    finally:
        await engine.dispose()


async def test_finalize_is_idempotent(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        sess = await svc.open_agent_session("org-1", "cs-1", "harnext", None, None, None)
        s1 = await svc.finalize_agent_session(sess.id, "completed", {"output_tokens": 42})
        assert s1.status == "closed" and s1.stop_reason == "completed"
        assert s1.ended_at is not None
        assert _maybe_json(s1.usage_json) == {"output_tokens": 42}
        s2 = await svc.finalize_agent_session(sess.id, "completed", {"output_tokens": 99})
        assert s2.status == "closed" and _maybe_json(s2.usage_json)["output_tokens"] == 99
    finally:
        await engine.dispose()


async def test_oversize_payload_is_truncated(tmp_path):
    svc, engine = await _svc(tmp_path, agent_event_max_bytes=64)
    try:
        sess = await svc.open_agent_session("org-1", "cs-1", "harnext", None, None, None)
        big = {"text": "x" * 5000}
        r = await svc.append_agent_events(sess.id, "org-1", [_ev(0, payload=big)])
        assert r["accepted"] == 1
        [event] = await svc.get_agent_session_events(sess.id)
        assert len(event.payload_json) <= 64
        # the reader tolerates the now-truncated (non-JSON) payload
        assert isinstance(_maybe_json(event.payload_json), str)
    finally:
        await engine.dispose()


async def test_tenant_isolation_on_session_lookup(tmp_path):
    """A session opened under org A is invisible to org B (the route layer keys
    its 404 on this org check)."""
    svc, engine = await _svc(tmp_path)
    try:
        a = await svc.open_agent_session("org-A", "cs-1", "harnext", None, None, None)
        sess = await svc.get_agent_session(a.id)
        assert sess.org_id == "org-A"
        # listing for the wrong org returns nothing
        assert await svc.list_agent_sessions("org-B") == []
        assert [s.id for s in await svc.list_agent_sessions("org-A")] == [a.id]
    finally:
        await engine.dispose()
