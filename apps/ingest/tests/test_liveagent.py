"""LiveAgent connector: base-URL coercion, the ticket→event walk, cursor
resume, message folding, error mapping, and the project-integration wiring."""

import httpx
import pytest
from meaninggrid_ingest.connectors.liveagent import (
    LiveAgentConnector,
    normalize_base_url,
)
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings
from meaninggrid_shared import init_db, make_engine, make_sessionmaker


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, event):
        self.sent.append((topic, event))


async def _svc(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    return SourceService(make_sessionmaker(engine), FakeProducer(), IngestSettings()), engine


# tickets the fake API returns, oldest-first (date_changed ASC)
_TICKETS = [
    {
        "id": "t10",
        "code": "AAA-10",
        "subject": "Login broken",
        "status": "N",
        "departmentid": "dept1",
        "owner_name": "Alice",
        "owner_email": "a@x.com",
        "tags": ["vip"],
        "date_created": "2026-06-01 09:00:00",
        "date_changed": "2026-06-01 10:00:00",
    },
    {
        "id": "t20",
        "code": "AAA-20",
        "subject": "Refund please",
        "status": "C",
        "departmentid": "dept1",
        "owner_name": "Bob",
        "owner_email": "b@x.com",
        "tags": [],
        "date_created": "2026-06-02 09:00:00",
        "date_changed": "2026-06-02 10:00:00",
    },
]

_MESSAGES = {
    "t10": [{"messages": [{"message": "<p>Help, I can't <b>log&nbsp;in</b></p>"}]}],
    "t20": [{"messages": [{"message": "Where is my refund?"}, {"message": "Following up"}]}],
}


def _fake_client(tickets):
    captured = {}

    async def fake_get(self, url, params=None, **kw):
        captured.setdefault("calls", []).append((url, params))

        class R:
            status_code = 200
            headers: dict = {}

            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

            def raise_for_status(self):
                pass

        if url == "/tickets":
            captured["tickets_params"] = params
            return R(tickets)
        if url.startswith("/tickets/") and url.endswith("/messages"):
            tid = url.split("/")[2]
            return R(_MESSAGES.get(tid, []))
        return R([])

    return fake_get, captured


def test_normalize_base_url():
    for raw, want in [
        ("https://acme.ladesk.com", "https://acme.ladesk.com"),
        ("https://acme.ladesk.com/", "https://acme.ladesk.com"),
        ("acme.ladesk.com", "https://acme.ladesk.com"),
        ("https://acme.ladesk.com/api/v3", "https://acme.ladesk.com"),
        ("https://acme.ladesk.com/api/v3/", "https://acme.ladesk.com"),
        ("http://localhost:8080/", "http://localhost:8080"),
    ]:
        assert normalize_base_url(raw) == want


async def test_connector_builds_events(monkeypatch):
    fake_get, captured = _fake_client(_TICKETS)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    res = await LiveAgentConnector().fetch(
        org_id="p1",
        config={"base_url": "https://acme.ladesk.com", "department_id": "dept1",
                "department_name": "Support"},
        secret="key-123",
        since=None,
    )

    assert [e.data["ticket_id"] for e in res.events] == ["t10", "t20"]
    assert all(e.mgtenant == "p1" for e in res.events)
    e = res.events[0]
    assert e.id == "liveagent-t10-20260601100000"
    assert e.source == "liveagent:dept1"
    assert e.type == "com.liveagent.ticket"
    assert e.subject == "department:Support"
    assert e.data["title"] == "Login broken"
    # message HTML is flattened into the body
    assert "log in" in e.data["body"] and "<" not in e.data["body"]
    assert res.events[1].data["body"].startswith("Where is my refund?")
    # cursor is the last ticket's "date_changed|id"
    assert res.cursor == "2026-06-02 10:00:00|t20"
    # department filter + ascending date sort were sent
    f = captured["tickets_params"]["_filters"]
    assert '["departmentid","E","dept1"]' in f
    assert captured["tickets_params"]["_sortDir"] == "ASC"


async def test_tag_filter_added(monkeypatch):
    fake_get, captured = _fake_client(_TICKETS)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await LiveAgentConnector().fetch(
        org_id="p1",
        config={"base_url": "https://acme.ladesk.com", "department_id": "dept1",
                "tag_id": "vip"},
        secret="key-123",
        since=None,
    )
    assert '["tags","CY","vip"]' in captured["tickets_params"]["_filters"]


async def test_cursor_resume_skips_boundary(monkeypatch):
    fake_get, captured = _fake_client(_TICKETS)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # resume exactly at t10 — it must be skipped, only t20 emitted
    res = await LiveAgentConnector().fetch(
        org_id="p1",
        config={"base_url": "https://acme.ladesk.com", "department_id": "dept1"},
        secret="key-123",
        since="2026-06-01 10:00:00|t10",
    )
    assert [e.data["ticket_id"] for e in res.events] == ["t20"]
    assert res.cursor == "2026-06-02 10:00:00|t20"
    # the inclusive date filter was sent
    assert '["date_changed","D>=","2026-06-01 10:00:00"]' in captured["tickets_params"]["_filters"]


async def test_empty_result_keeps_cursor(monkeypatch):
    fake_get, _ = _fake_client([])
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    res = await LiveAgentConnector().fetch(
        org_id="p1",
        config={"base_url": "https://acme.ladesk.com", "department_id": "dept1"},
        secret="key-123",
        since="2026-06-02 10:00:00|t20",
    )
    assert res.events == []
    assert res.cursor == "2026-06-02 10:00:00|t20"


async def test_missing_key_or_department_raises():
    c = LiveAgentConnector()
    with pytest.raises(RuntimeError, match="API key"):
        await c.fetch(org_id="p1", config={"base_url": "https://x", "department_id": "d"},
                      secret=None, since=None)
    with pytest.raises(RuntimeError, match="department"):
        await c.fetch(org_id="p1", config={"base_url": "https://x"}, secret="k", since=None)


def test_raise_for_status():
    class R:
        def __init__(self, code, headers=None):
            self.status_code = code
            self.headers = headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

    for code, frag in [(401, "API key"), (403, "permission"), (404, "base URL")]:
        with pytest.raises(RuntimeError) as ei:
            LiveAgentConnector._raise_for_liveagent(R(code))
        assert frag in str(ei.value)
    with pytest.raises(RuntimeError) as ei:
        LiveAgentConnector._raise_for_liveagent(R(429, {"Retry-After": "7"}))
    assert "rate limit" in str(ei.value) and "7" in str(ei.value)
    LiveAgentConnector._raise_for_liveagent(R(200))  # ok → no raise


async def test_source_uses_project_integration(tmp_path):
    """create_source must snapshot the project's base URL into config and its
    API key into the source secret (so the connector stays self-contained)."""
    svc, engine = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        await svc.set_liveagent_integration(p.id, "https://acme.ladesk.com", "key-999")
        src = await svc.create_source(
            p.id, "liveagent", {"department_id": "dept1", "department_name": "Support"}
        )
        import json

        cfg = json.loads(src.config_json)
        assert cfg["base_url"] == "https://acme.ladesk.com"
        assert cfg["department_id"] == "dept1"
        assert src.secret == "key-999"  # defaulted from the integration
    finally:
        await engine.dispose()
