"""Sitemap connector + distributed crawler: parsing, incremental selection,
polite inline crawl (robots / non-OK / backoff handling), and the Celery
discover→fan-out / per-URL persist paths."""

from __future__ import annotations

import gzip
from types import SimpleNamespace

import httpx
import pytest
from meaninggrid_ingest import crawler
from meaninggrid_ingest.connectors.sitemap import (
    SitemapConnector,
    SitemapEntry,
    TransientCrawlError,
    _safe_cursor,
    extract_text,
    extract_title,
    page_event,
    parse_sitemap,
    select_entries,
)
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings
from meaninggrid_shared import init_db, make_engine, make_sessionmaker

# -- test doubles -----------------------------------------------------------


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, event):
        self.sent.append((topic, event))


class Resp:
    """Minimal httpx.Response stand-in for the bits the connector touches."""

    def __init__(self, status_code=200, *, text="", content=None, headers=None):
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode()
        self.headers = headers or {}


async def _svc(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    producer = FakeProducer()
    return SourceService(make_sessionmaker(engine), producer, IngestSettings()), engine, producer


# -- sitemap XML parsing ----------------------------------------------------
URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>/a</loc><lastmod>2026-06-05T10:00:00Z</lastmod></url>
  <url><loc>https://ex.com/b</loc><lastmod>2026-06-01</lastmod></url>
  <url><loc>https://ex.com/c</loc></url>
</urlset>"""

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://ex.com/posts.xml</loc></sitemap>
  <sitemap><loc>https://ex.com/pages.xml</loc></sitemap>
</sitemapindex>"""


def test_parse_urlset_resolves_relative_and_lastmod():
    entries, children = parse_sitemap(URLSET, url="https://ex.com/sitemap.xml")
    assert children == []
    locs = [(e.loc, e.lastmod) for e in entries]
    # relative /a resolved against the sitemap URL; lastmod normalized to ISO
    assert locs[0] == ("https://ex.com/a", "2026-06-05T10:00:00+00:00")
    assert locs[1] == ("https://ex.com/b", "2026-06-01T00:00:00")  # bare date → midnight
    assert locs[2] == ("https://ex.com/c", None)


def test_parse_sitemapindex_returns_children():
    entries, children = parse_sitemap(INDEX, url="https://ex.com/sitemap.xml")
    assert entries == []
    assert children == ["https://ex.com/posts.xml", "https://ex.com/pages.xml"]


def test_parse_handles_gzip_and_no_namespace():
    gz = gzip.compress(URLSET)
    # gzip magic bytes are detected even when the URL doesn't end in .gz
    entries, _ = parse_sitemap(gz, url="https://ex.com/sitemap.xml")
    assert [e.loc for e in entries] == ["https://ex.com/a", "https://ex.com/b", "https://ex.com/c"]
    # a non-namespaced sitemap parses too
    plain = b"<urlset><url><loc>https://ex.com/z</loc></url></urlset>"
    entries2, _ = parse_sitemap(plain, url="https://ex.com/sitemap.xml")
    assert [e.loc for e in entries2] == ["https://ex.com/z"]


def test_parse_malformed_is_empty_not_raising():
    assert parse_sitemap(b"<not xml", url="https://ex.com/s.xml") == ([], [])


# -- incremental selection --------------------------------------------------
def test_select_entries_oldest_first_and_cap():
    entries = [
        SitemapEntry("https://ex.com/a", "2026-06-05T00:00:00+00:00"),
        SitemapEntry("https://ex.com/b", "2026-06-01T00:00:00+00:00"),
        SitemapEntry("https://ex.com/c", None),  # undated → always a candidate
    ]
    # no cursor, no cap: every page, OLDEST dated first, undated trailing
    assert [e.loc for e in select_entries(entries, since=None, max_pages=None)] == [
        "https://ex.com/b",
        "https://ex.com/a",
        "https://ex.com/c",
    ]
    # incremental: only pages newer than the cursor (b is older → dropped)
    picked = select_entries(entries, since="2026-06-02T00:00:00+00:00", max_pages=None)
    assert [e.loc for e in picked] == ["https://ex.com/a", "https://ex.com/c"]
    # max_pages caps to the OLDEST N (so the watermark walks forward, no skips)
    assert [e.loc for e in select_entries(entries, since=None, max_pages=1)] == ["https://ex.com/b"]


def test_safe_cursor_only_advances_past_fully_crawled():
    a = SitemapEntry("a", "2026-06-01T00:00:00+00:00")
    b = SitemapEntry("b", "2026-06-05T00:00:00+00:00")
    c = SitemapEntry("c", None)
    # nothing dropped → cursor = newest crawled lastmod
    assert _safe_cursor([a, b], None, None) == "2026-06-05T00:00:00+00:00"
    # dropped page has a *newer* lastmod (clean boundary) → cursor = newest crawled
    dropped_newer = SitemapEntry("d", "2026-06-09T00:00:00+00:00")
    assert _safe_cursor([a, b], dropped_newer, None) == "2026-06-05T00:00:00+00:00"
    # dropped page SHARES the newest crawled lastmod → that group is split, so the
    # cursor backs off to the last fully-crawled timestamp (else the tail is lost)
    dropped_tie = SitemapEntry("e", "2026-06-05T00:00:00+00:00")
    assert _safe_cursor([a, b], dropped_tie, None) == "2026-06-01T00:00:00+00:00"
    # whole selection is one split group → don't advance at all
    b2 = SitemapEntry("b2", "2026-06-05T00:00:00+00:00")
    assert _safe_cursor([b, b2], dropped_tie, None) is None
    # undated-only selection never advances the (lastmod-based) cursor
    assert _safe_cursor([c], None, "2026-06-01T00:00:00+00:00") == "2026-06-01T00:00:00+00:00"


def test_capped_polls_eventually_cover_all_pages():
    """The coverage guarantee: capped polls page forward through the whole set via
    the cursor, never permanently skipping the tail (even across a same-lastmod
    boundary). Two pages share a lastmod to exercise the tie back-off."""
    entries = [
        SitemapEntry("https://ex.com/p1", "2026-06-01T00:00:00+00:00"),
        SitemapEntry("https://ex.com/p2", "2026-06-02T00:00:00+00:00"),
        SitemapEntry("https://ex.com/p3", "2026-06-02T00:00:00+00:00"),  # tie with p2
        SitemapEntry("https://ex.com/p4", "2026-06-03T00:00:00+00:00"),
    ]

    def poll(cursor, cap):
        ordered = select_entries(entries, since=cursor, max_pages=None)
        selected = ordered[:cap]
        dropped = ordered[cap] if len(ordered) > cap else None
        return [e.loc for e in selected], _safe_cursor(selected, dropped, cursor)

    seen, cursor, guard = [], None, 0
    while guard < 10:
        guard += 1
        locs, cursor = poll(cursor, cap=2)
        new = [u for u in locs if u not in seen]
        seen += new
        if not new:
            break
    assert set(seen) == {f"https://ex.com/p{i}" for i in range(1, 5)}  # all four covered


# -- text extraction + event shape ------------------------------------------
def test_extract_title_and_text():
    html = (
        "<html><head><title>Hello &amp; Bye</title><style>.x{}</style></head>"
        "<body><script>var x=1</script><h1>Hi</h1><p>World &amp; co</p></body></html>"
    )
    assert extract_title(html) == "Hello & Bye"
    text = extract_text(html)
    assert "var x" not in text and ".x{}" not in text  # script/style dropped
    assert "Hi World & co" in text


def test_page_event_id_stable_per_url_and_lastmod():
    e1 = page_event(
        org_id="org1",
        site="ex.com",
        url="https://ex.com/a",
        title="T",
        text="body",
        status=200,
        lastmod="2026-06-05T00:00:00+00:00",
    )
    assert e1.source == "sitemap:ex.com"
    assert e1.type == "com.web.page"
    assert e1.subject == "site:ex.com"
    assert e1.mgtenant == "org1"
    assert e1.data["url"] == "https://ex.com/a"
    # same url + same lastmod → same id (re-crawl dedups)
    e2 = page_event(
        org_id="org1",
        site="ex.com",
        url="https://ex.com/a",
        title="T",
        text="body",
        status=200,
        lastmod="2026-06-05T00:00:00+00:00",
    )
    assert e1.id == e2.id
    # a changed page (new lastmod) → new id
    e3 = page_event(
        org_id="org1",
        site="ex.com",
        url="https://ex.com/a",
        title="T",
        text="body",
        status=200,
        lastmod="2026-06-09T00:00:00+00:00",
    )
    assert e3.id != e1.id


# -- inline polite crawl (fetch) --------------------------------------------
SITEMAP_FOR_CRAWL = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ex.com/a</loc><lastmod>2026-06-05T00:00:00Z</lastmod></url>
  <url><loc>https://ex.com/b</loc><lastmod>2026-06-01T00:00:00Z</lastmod></url>
  <url><loc>https://ex.com/private/secret</loc><lastmod>2026-06-04T00:00:00Z</lastmod></url>
  <url><loc>https://ex.com/slow</loc><lastmod>2026-06-03T00:00:00Z</lastmod></url>
  <url><loc>https://ex.com/img.png</loc><lastmod>2026-06-02T00:00:00Z</lastmod></url>
</urlset>"""

ROBOTS = "User-agent: *\nDisallow: /private\n"


def _router(get_calls=None):
    """An httpx.AsyncClient.get replacement that routes by URL to the right Resp."""

    async def fake_get(self, url, *args, **kwargs):
        if get_calls is not None:
            get_calls.append(url)
        if url.endswith("/robots.txt"):
            return Resp(200, text=ROBOTS)
        if url.endswith("/sitemap.xml"):
            return Resp(200, content=SITEMAP_FOR_CRAWL, headers={"content-type": "application/xml"})
        if url.endswith("/slow"):
            return Resp(429, headers={"Retry-After": "5"})  # site asks us to back off
        if url.endswith("/img.png"):
            return Resp(200, text="\x89PNG...", headers={"content-type": "image/png"})
        return Resp(
            200,
            text=f"<html><head><title>{url}</title></head><body>hi {url}</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    return fake_get


async def test_fetch_inline_crawl_respects_robots_status_and_backoff(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(httpx.AsyncClient, "get", _router(calls))
    conn = SitemapConnector(delay=0, concurrency=4, respect_robots=True)
    res = await conn.fetch(
        org_id="org1", config={"sitemap_url": "https://ex.com/sitemap.xml"}, secret=None, since=None
    )
    crawled = {e.data["url"] for e in res.events}
    # /a and /b crawled; /private/* filtered by robots; /slow 429-skipped; /img.png non-HTML-skipped
    assert crawled == {"https://ex.com/a", "https://ex.com/b"}
    assert not any("private" in u for u in calls)  # disallowed page never even requested
    assert all(e.type == "com.web.page" for e in res.events)
    assert res.cursor == "2026-06-05T00:00:00+00:00"  # high-water mark across discovery
    assert res.events == sorted(res.events, key=lambda e: e.time)  # chronological


async def test_fetch_incremental_only_changed(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "get", _router())
    conn = SitemapConnector(delay=0, respect_robots=True)
    res = await conn.fetch(
        org_id="org1",
        config={"sitemap_url": "https://ex.com/sitemap.xml"},
        secret=None,
        # /a (06-05) is the only allowed page newer than the cursor: /private (06-04)
        # is robots-blocked; /slow (06-03), /img (06-02), /b (06-01) are all older.
        since="2026-06-03T12:00:00+00:00",
    )
    assert {e.data["url"] for e in res.events} == {"https://ex.com/a"}


async def test_crawl_page_raises_transient_on_429():
    async def fake_get(self, url, *a, **k):
        return Resp(503, headers={"Retry-After": "7"})

    import unittest.mock as m

    with m.patch.object(httpx.AsyncClient, "get", fake_get):
        async with httpx.AsyncClient() as client:
            with pytest.raises(TransientCrawlError) as ei:
                await SitemapConnector().crawl_page(
                    client, SitemapEntry("https://ex.com/x", None), org_id="o", site="ex.com"
                )
    assert ei.value.retry_after == 7.0 and ei.value.status == 503


# -- service wiring ---------------------------------------------------------
async def test_create_sitemap_source_needs_no_secret(tmp_path):
    svc, engine, _ = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        src = await svc.create_source(
            p.id, "sitemap", {"sitemap_url": "https://ex.com/sitemap.xml"}, None
        )
        assert src.kind == "sitemap" and src.secret is None and src.status == "active"
    finally:
        await engine.dispose()


async def test_record_event_writes_without_moving_cursor(tmp_path):
    """The per-page write used by the crawl fan-out: produce + record + stamp
    last_sync, but leave the cursor (advanced up front by crawl_sitemap) alone."""
    svc, engine, producer = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        src = await svc.create_source(
            p.id, "sitemap", {"sitemap_url": "https://ex.com/sitemap.xml"}, None
        )
        await svc.set_cursor(src.id, "2026-06-05T00:00:00+00:00")
        ev = page_event(
            org_id=p.id,
            site="ex.com",
            url="https://ex.com/a",
            title="T",
            text="b",
            status=200,
            lastmod="2026-06-05T00:00:00+00:00",
        )
        assert await svc.record_event(src.id, ev) is True
        assert producer.sent[-1][1].id == ev.id
        assert len(await svc.list_events(p.id)) == 1
        refreshed = await svc.get_source(src.id)
        assert refreshed.last_sync_at is not None
        assert refreshed.cursor == "2026-06-05T00:00:00+00:00"  # untouched
        # a vanished source is a no-op, not an error
        assert await svc.record_event("does-not-exist", ev) is False
    finally:
        await engine.dispose()


# -- celery: per-URL persist + discover/fan-out -----------------------------
async def test_crawl_one_persists_event(tmp_path, monkeypatch):
    svc, engine, producer = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        src = await svc.create_source(
            p.id, "sitemap", {"sitemap_url": "https://ex.com/sitemap.xml"}, None
        )
        monkeypatch.setattr(httpx.AsyncClient, "get", _router())
        rt = SimpleNamespace(service=svc, settings=IngestSettings())
        ok = await crawler._crawl_one(
            rt, src.id, "https://ex.com/a", "2026-06-05T00:00:00+00:00", "ex.com", p.id
        )
        assert ok is True
        assert producer.sent[-1][1].type == "com.web.page"
        assert len(await svc.list_events(p.id)) == 1
        # a non-HTML asset is skipped (no event)
        assert (
            await crawler._crawl_one(rt, src.id, "https://ex.com/img.png", None, "ex.com", p.id)
            is False
        )
    finally:
        await engine.dispose()


def test_crawl_sitemap_fans_out_and_advances_cursor(tmp_path, monkeypatch):
    """crawl_sitemap discovers, enqueues one spaced crawl_url per page, and moves
    the cursor up front — without a live broker (apply_async is captured)."""
    settings = IngestSettings(crawl_delay_seconds=2)
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    producer = FakeProducer()
    svc = SourceService(make_sessionmaker(engine), producer, settings)
    rt = crawler._Runtime(svc, settings)  # real loop-thread bridge, no Kafka producer
    try:
        rt.run(init_db(engine))
        u = rt.run(svc.register("a@b.com", "hunter2", "A"))
        p = rt.run(svc.create_project(u.id, "P"))
        src = rt.run(
            svc.create_source(p.id, "sitemap", {"sitemap_url": "https://ex.com/sitemap.xml"}, None)
        )
        monkeypatch.setattr(crawler, "_RT", rt)

        async def fake_discover(self, *, config, since, client=None, max_pages=None):
            assert max_pages is None  # the celery path must crawl ALL pages, uncapped
            return (
                [
                    SitemapEntry("https://ex.com/a", "2026-06-05T00:00:00+00:00"),
                    SitemapEntry("https://ex.com/b", None),
                ],
                "2026-06-05T00:00:00+00:00",
            )

        monkeypatch.setattr(SitemapConnector, "discover", fake_discover)
        enqueued: list[tuple] = []
        monkeypatch.setattr(
            crawler.crawl_url,
            "apply_async",
            lambda args, **kw: enqueued.append((args, kw)),
        )

        result = crawler.crawl_sitemap.apply(args=[src.id])
        assert result.successful(), result.traceback
        assert result.get()["enqueued"] == 2

        # one crawl_url per page, spaced by countdown = i * delay
        assert [a[0][1] for a in enqueued] == ["https://ex.com/a", "https://ex.com/b"]
        assert [a[1]["countdown"] for a in enqueued] == [0, 2]
        # cursor advanced up front so a concurrent poll won't re-discover these
        assert rt.run(svc.get_source(src.id)).cursor == "2026-06-05T00:00:00+00:00"
    finally:
        rt.run(engine.dispose())
