"""Ingest: GitHub connector event-building + sync service (fakes, no network)."""

from datetime import UTC, datetime

from meaninggrid_ingest.connectors.base import FetchResult
from meaninggrid_ingest.connectors.github import GitHubConnector
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings
from meaninggrid_shared import CloudEvent, init_db, make_engine, make_sessionmaker


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, ev):
        self.sent.append((topic, ev))


async def test_github_connector_builds_events(monkeypatch):
    async def fake_get(self, client, url, since, **params):
        if url.endswith("/issues"):
            return [
                {
                    "number": 1,
                    "title": "Bug",
                    "state": "open",
                    "body": "x",
                    "labels": [{"name": "P0"}],
                    "user": {"login": "alice"},
                    "html_url": "u",
                    "updated_at": "2026-06-01T00:00:00Z",
                }
            ]
        if url.endswith("/comments"):
            return [
                {
                    "id": 99,
                    "body": "c",
                    "user": {"login": "bob"},
                    "html_url": "u",
                    "updated_at": "2026-06-02T00:00:00Z",
                    "issue_url": "iu",
                }
            ]
        if url.endswith("/commits"):
            return [
                {
                    "sha": "abc",
                    "html_url": "u",
                    "commit": {
                        "message": "m",
                        "author": {"name": "carol", "date": "2026-06-03T00:00:00Z"},
                    },
                }
            ]
        return []

    monkeypatch.setattr(GitHubConnector, "_get", fake_get)
    res = await GitHubConnector(per_page=5).fetch(
        org_id="acme", config={"repo": "acme/web"}, secret=None, since=None
    )

    assert len(res.events) == 3
    assert {e.type for e in res.events} == {
        "com.github.issue",
        "com.github.issue_comment",
        "com.github.commit",
    }
    assert all(e.subject == "repo:acme/web" and e.mgtenant == "acme" for e in res.events)
    assert [e.time for e in res.events] == sorted(e.time for e in res.events)  # chronological
    assert res.cursor == "2026-06-03T00:00:00+00:00"


async def test_sync_produces_and_records(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    sm = make_sessionmaker(engine)
    producer = FakeProducer()
    svc = SourceService(sm, producer, IngestSettings())

    ev = CloudEvent(
        id="github-commit-acme/web-abc",
        source="github:acme/web",
        type="com.github.commit",
        subject="repo:acme/web",
        time=datetime.now(UTC),
        mgtenant="acme",
        data={},
    )
    monkeypatch.setattr(
        "meaninggrid_ingest.service.get_connector",
        lambda kind, **kw: _FakeConnector([ev], cursor="c1"),
    )

    src = await svc.create_source("acme", "github", {"repo": "acme/web"}, None)
    n = await svc.sync(src.id)

    assert n == 1
    assert producer.sent and producer.sent[0][1].id == ev.id
    again = await svc.get_source(src.id)
    assert again is not None and again.cursor == "c1" and again.last_sync_at is not None
    events = await svc.list_events("acme")
    assert len(events) == 1 and events[0].event_id == ev.id

    # re-sync the same event → no duplicate IngestedEvent row (merge by PK)
    await svc.sync(src.id)
    assert len(await svc.list_events("acme")) == 1

    await engine.dispose()


class _FakeConnector:
    kind = "github"

    def __init__(self, events, cursor):
        self._events = events
        self._cursor = cursor

    async def fetch(self, *, org_id, config, secret, since):
        return FetchResult(events=self._events, cursor=self._cursor)
