"""Single-URL connector: one-page fetch + event shape, change-detection via the
page's Last-Modified/ETag/content-hash cursor, non-HTML / error handling, and the
no-secret service wiring."""

from __future__ import annotations

import httpx
import pytest
from harnext_ingest.connectors.url import UrlConnector, normalize_url, page_event
from harnext_ingest.service import SourceService
from harnext_ingest.settings import IngestSettings
from harnext_shared import init_db, make_engine, make_sessionmaker


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, event):
        self.sent.append((topic, event))


class Resp:
    """Minimal httpx.Response stand-in for the bits the connector touches."""

    def __init__(self, status_code=200, *, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


async def _svc(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    producer = FakeProducer()
    return SourceService(make_sessionmaker(engine), producer, IngestSettings()), engine, producer


PAGE = (
    "<html><head><title>Docs &amp; Guides</title><style>.x{}</style></head>"
    "<body><script>var x=1</script><h1>Hi</h1><p>Read me &amp; weep</p></body></html>"
)
HTML = {"content-type": "text/html; charset=utf-8"}


def test_normalize_url_prepends_scheme():
    assert normalize_url("example.com/a") == "https://example.com/a"
    assert normalize_url("  http://ex.com ") == "http://ex.com"
    assert normalize_url("https://ex.com/x") == "https://ex.com/x"


def test_page_event_shape_and_id_tracks_token():
    e1 = page_event(
        org_id="org1",
        site="ex.com",
        url="https://ex.com/a",
        title="T",
        text="body",
        status=200,
        token='W/"abc"',
    )
    assert e1.source == "url:ex.com"  # distinct from sitemap:, its own anomaly bucket
    assert e1.type == "com.web.page"  # same type → builder/classifier treat it as a page
    assert e1.subject == "site:ex.com"  # folds into the same site entity as a sitemap
    assert e1.data["url"] == "https://ex.com/a"
    # same url + same token → same id (unchanged re-fetch dedups)
    e2 = page_event(
        org_id="org1",
        site="ex.com",
        url="https://ex.com/a",
        title="T",
        text="body",
        status=200,
        token='W/"abc"',
    )
    assert e1.id == e2.id
    # token moved (page changed) → fresh id so the builder reprocesses
    e3 = page_event(
        org_id="org1",
        site="ex.com",
        url="https://ex.com/a",
        title="T",
        text="body",
        status=200,
        token='W/"def"',
    )
    assert e3.id != e1.id


async def test_fetch_single_page_emits_one_event(monkeypatch):
    async def fake_get(self, url, *a, **k):
        return Resp(
            200, text=PAGE, headers={**HTML, "Last-Modified": "Mon, 09 Jun 2026 00:00:00 GMT"}
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    res = await UrlConnector().fetch(
        org_id="org1", config={"url": "https://ex.com/docs"}, secret=None, since=None
    )
    assert len(res.events) == 1
    ev = res.events[0]
    assert ev.type == "com.web.page" and ev.source == "url:ex.com"
    assert ev.data["title"] == "Docs & Guides"
    assert "Hi Read me & weep" in ev.data["text"] and "var x" not in ev.data["text"]
    # cursor is the server validator, so an unchanged re-poll can short-circuit
    assert res.cursor == "Mon, 09 Jun 2026 00:00:00 GMT"


async def test_fetch_unchanged_emits_nothing(monkeypatch):
    async def fake_get(self, url, *a, **k):
        return Resp(200, text=PAGE, headers={**HTML, "ETag": 'W/"v1"'})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    conn = UrlConnector()
    first = await conn.fetch(
        org_id="o", config={"url": "https://ex.com/a"}, secret=None, since=None
    )
    assert first.cursor == 'W/"v1"' and len(first.events) == 1
    # re-poll with the stored cursor: same ETag → no new event, cursor held
    again = await conn.fetch(
        org_id="o", config={"url": "https://ex.com/a"}, secret=None, since=first.cursor
    )
    assert again.events == [] and again.cursor == 'W/"v1"'


async def test_fetch_changed_content_without_validators_reemits(monkeypatch):
    """No Last-Modified/ETag → the cursor is a content hash, so an edited page
    still produces a new event (and a new id) on the next poll."""
    bodies = iter([PAGE, PAGE.replace("Read me", "Rewritten")])

    async def fake_get(self, url, *a, **k):
        return Resp(200, text=next(bodies), headers=HTML)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    conn = UrlConnector()
    first = await conn.fetch(
        org_id="o", config={"url": "https://ex.com/a"}, secret=None, since=None
    )
    assert first.cursor.startswith("sha1:")
    second = await conn.fetch(
        org_id="o", config={"url": "https://ex.com/a"}, secret=None, since=first.cursor
    )
    assert len(second.events) == 1 and second.cursor != first.cursor
    assert second.events[0].id != first.events[0].id


async def test_fetch_non_html_and_http_error_raise(monkeypatch):
    async def asset(self, url, *a, **k):
        return Resp(200, text="\x89PNG", headers={"content-type": "image/png"})

    monkeypatch.setattr(httpx.AsyncClient, "get", asset)
    with pytest.raises(RuntimeError, match="not a readable"):
        await UrlConnector().fetch(
            org_id="o", config={"url": "https://ex.com/x.png"}, secret=None, since=None
        )

    async def missing(self, url, *a, **k):
        return Resp(404, headers=HTML)

    monkeypatch.setattr(httpx.AsyncClient, "get", missing)
    with pytest.raises(RuntimeError, match="HTTP 404"):
        await UrlConnector().fetch(
            org_id="o", config={"url": "https://ex.com/gone"}, secret=None, since=None
        )


async def test_fetch_missing_url_in_config_raises():
    with pytest.raises(RuntimeError, match="needs a 'url'"):
        await UrlConnector().fetch(org_id="o", config={}, secret=None, since=None)


async def test_create_url_source_needs_no_secret(tmp_path):
    svc, engine, _ = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        src = await svc.create_source(p.id, "url", {"url": "https://ex.com/a"}, None)
        assert src.kind == "url" and src.secret is None and src.status == "active"
    finally:
        await engine.dispose()
