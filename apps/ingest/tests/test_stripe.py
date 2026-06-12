"""Stripe connector: the event→CloudEvent walk, cursor resume (ending_before),
credential verification, error mapping, and the project-integration wiring."""

import json

import httpx
import pytest
from meaninggrid_ingest.connectors.base import RateLimitedError
from meaninggrid_ingest.connectors.stripe import StripeConnector, verify_credentials
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


# Stripe returns events newest-first; evt_2 is newer than evt_1.
_EVENTS = [
    {
        "id": "evt_2",
        "type": "charge.succeeded",
        "created": 1717322400,
        "livemode": False,
        "api_version": "2024-06-20",
        "data": {
            "object": {
                "object": "charge",
                "id": "ch_2",
                "amount": 2000,
                "currency": "usd",
                "status": "succeeded",
            }
        },
    },
    {
        "id": "evt_1",
        "type": "customer.created",
        "created": 1717318800,
        "livemode": False,
        "api_version": "2024-06-20",
        "data": {"object": {"object": "customer", "id": "cus_1", "email": "a@x.com"}},
    },
]

_ACCOUNT = {
    "id": "acct_123",
    "email": "owner@acme.com",
    "business_profile": {"name": "Acme Payments"},
    "settings": {"dashboard": {"display_name": "Acme Inc"}},
}


def _fake_client(events, account=None):
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

        if url == "/v1/events":
            captured["events_params"] = params
            return R({"object": "list", "data": events, "has_more": False})
        if url == "/v1/account":
            return R(account or {})
        return R({"object": "list", "data": []})

    return fake_get, captured


async def test_connector_builds_events(monkeypatch):
    fake_get, captured = _fake_client(_EVENTS)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    res = await StripeConnector().fetch(
        org_id="p1",
        config={"account_name": "Acme Inc"},
        secret="rk_test_123",
        since=None,
    )

    # emitted oldest-first (customer.created precedes charge.succeeded)
    assert [e.data["event_id"] for e in res.events] == ["evt_1", "evt_2"]
    assert all(e.mgtenant == "p1" for e in res.events)
    cust = res.events[0]
    assert cust.id == "stripe-evt_1"
    assert cust.source == "stripe:Acme Inc"
    assert cust.type == "com.stripe.event"
    assert cust.subject == "stripe:customer"
    assert cust.data["event_type"] == "customer.created"
    assert cust.data["object"] == "customer" and cust.data["object_id"] == "cus_1"
    assert cust.data["email"] == "a@x.com"
    charge = res.events[1]
    assert charge.subject == "stripe:charge"
    assert charge.data["amount"] == 2000 and charge.data["currency"] == "usd"
    assert charge.data["status"] == "succeeded"
    # the full object is folded into a clipped JSON summary
    assert "ch_2" in charge.data["summary"]
    # cursor is the newest (first) event id — the next ending_before watermark
    assert res.cursor == "evt_2"
    # first sync sends no cursor
    assert "ending_before" not in captured["events_params"]


async def test_cursor_resume_sends_ending_before(monkeypatch):
    fake_get, captured = _fake_client(_EVENTS)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    res = await StripeConnector().fetch(
        org_id="p1",
        config={"account_name": "Acme Inc"},
        secret="rk_test_123",
        since="evt_0",
    )
    assert captured["events_params"]["ending_before"] == "evt_0"
    assert res.cursor == "evt_2"


async def test_empty_result_keeps_cursor(monkeypatch):
    fake_get, _ = _fake_client([])
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    res = await StripeConnector().fetch(
        org_id="p1",
        config={"account_name": "Acme Inc"},
        secret="rk_test_123",
        since="evt_9",
    )
    assert res.events == []
    assert res.cursor == "evt_9"


async def test_missing_key_raises():
    with pytest.raises(RuntimeError, match="API key"):
        await StripeConnector().fetch(org_id="p1", config={}, secret=None, since=None)


async def test_account_name_falls_back(monkeypatch):
    """With no account_name in config the source label degrades gracefully."""
    fake_get, _ = _fake_client(_EVENTS)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    res = await StripeConnector().fetch(org_id="p1", config={}, secret="rk", since=None)
    assert res.events[0].source == "stripe:account"


async def test_verify_credentials(monkeypatch):
    fake_get, captured = _fake_client(_EVENTS, account=_ACCOUNT)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    info = await verify_credentials("rk_test_123")
    assert info["name"] == "Acme Inc"  # dashboard display_name preferred
    # it probed both the events list (the required permission) and the account
    assert {c[0] for c in captured["calls"]} == {"/v1/events", "/v1/account"}


async def test_verify_credentials_account_optional(monkeypatch):
    """A key without Account read still verifies — name falls back."""

    async def fake_get(self, url, params=None, **kw):
        class R:
            headers: dict = {}

            def __init__(self, code, data):
                self.status_code = code
                self._data = data

            def json(self):
                return self._data

            def raise_for_status(self):
                pass

        if url == "/v1/events":
            return R(200, {"object": "list", "data": []})
        return R(403, {})  # /v1/account forbidden

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    info = await verify_credentials("rk_test_123")
    assert info["name"] == "Stripe account"


def test_raise_for_stripe():
    class R:
        def __init__(self, code, headers=None):
            self.status_code = code
            self.headers = headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

    for code, frag in [(401, "invalid"), (403, "permission")]:
        with pytest.raises(RuntimeError) as ei:
            StripeConnector._raise_for_stripe(R(code))
        assert frag in str(ei.value)
    with pytest.raises(RateLimitedError) as ei:
        StripeConnector._raise_for_stripe(R(429, {"Retry-After": "7"}))
    assert ei.value.retry_after == 7.0
    StripeConnector._raise_for_stripe(R(200))  # ok → no raise


async def test_source_uses_project_integration(tmp_path):
    """create_source must snapshot the project's account name into config and its
    Restricted key into the source secret (so the connector stays self-contained)."""
    svc, engine = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        await svc.set_stripe_integration(p.id, "Acme Inc", "rk_live_999")
        src = await svc.create_source(p.id, "stripe", {})
        cfg = json.loads(src.config_json)
        assert cfg["account_name"] == "Acme Inc"
        assert src.secret == "rk_live_999"  # defaulted from the integration
    finally:
        await engine.dispose()
