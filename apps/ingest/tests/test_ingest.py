"""Ingest: connector event-building, auth/projects, sync, OAuth token reuse."""

from datetime import UTC, datetime

from meaninggrid_ingest import oauth
from meaninggrid_ingest.connectors.base import FetchResult
from meaninggrid_ingest.connectors.github import GitHubConnector
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings
from meaninggrid_shared import CloudEvent, init_db, make_engine, make_sessionmaker


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, event):
        self.sent.append((topic, event))


async def _svc(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    producer = FakeProducer()
    return SourceService(make_sessionmaker(engine), producer, IngestSettings()), engine, producer


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
        org_id="p1", config={"repo": "acme/web"}, secret=None, since=None
    )
    assert len(res.events) == 3
    assert {e.type for e in res.events} == {
        "com.github.issue",
        "com.github.issue_comment",
        "com.github.commit",
    }
    assert all(e.mgtenant == "p1" for e in res.events)


async def test_login_and_projects(tmp_path):
    svc, engine, _ = await _svc(tmp_path)
    try:
        u1 = await svc.login("alice")
        u1b = await svc.login("alice")  # idempotent
        assert u1.id == u1b.id
        p = await svc.create_project(u1.id, "My Project")
        assert p.owner_id == u1.id
        projects = await svc.list_projects(u1.id)
        assert [x.id for x in projects] == [p.id]
    finally:
        await engine.dispose()


async def test_sync_under_project(tmp_path, monkeypatch):
    svc, engine, producer = await _svc(tmp_path)
    try:
        user = await svc.login("alice")
        proj = await svc.create_project(user.id, "P")
        ev = CloudEvent(
            id="github-commit-acme/web-abc",
            source="github:acme/web",
            type="com.github.commit",
            subject="repo:acme/web",
            time=datetime.now(UTC),
            mgtenant=proj.id,
            data={},
        )
        monkeypatch.setattr(
            "meaninggrid_ingest.service.get_connector",
            lambda kind, **kw: _FakeConnector([ev], "c1"),
        )
        src = await svc.create_source(proj.id, "github", {"repo": "acme/web"}, None)
        n = await svc.sync(src.id)
        assert n == 1
        assert producer.sent[0][1].id == ev.id
        assert len(await svc.list_events(proj.id)) == 1
    finally:
        await engine.dispose()


async def test_oauth_token_reuse(tmp_path):
    svc, engine, _ = await _svc(tmp_path)
    try:
        user = await svc.login("alice")
        proj = await svc.create_project(user.id, "P")
        await svc.set_github_token(proj.id, "alice", "ghp_secret")
        # creating a source without a secret reuses the project's OAuth token
        src = await svc.create_source(proj.id, "github", {"repo": "a/b"}, None)
        assert src.secret == "ghp_secret"
        p = await svc.get_project(proj.id)
        assert p is not None and p.github_login == "alice" and p.github_token == "ghp_secret"
    finally:
        await engine.dispose()


def test_oauth_state():
    s = oauth.new_state("proj1", "github")
    assert oauth.consume_state(s) == ("proj1", "github")
    assert oauth.consume_state(s) is None  # single-use
    assert oauth.consume_state("bogus") is None


class _FakeConnector:
    kind = "github"

    def __init__(self, events, cursor):
        self._events = events
        self._cursor = cursor

    async def fetch(self, *, org_id, config, secret, since):
        return FetchResult(events=self._events, cursor=self._cursor)
