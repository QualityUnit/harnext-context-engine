"""Ingest: connectors, auth (register/login/Google), projects, sync, OAuth."""

from datetime import UTC, datetime

import pytest
from meaninggrid_ingest import oauth
from meaninggrid_ingest.connectors.base import FetchResult
from meaninggrid_ingest.connectors.github import GitHubConnector
from meaninggrid_ingest.security import create_token, decode_token, hash_password, verify_password
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


def test_security_primitives():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h)
    assert not verify_password("wrong", h)
    tok = create_token("user-1", "secret", 1)
    assert decode_token(tok, "secret") == "user-1"
    assert decode_token(tok, "other-secret") is None
    assert decode_token("garbage", "secret") is None


async def test_register_login_projects(tmp_path):
    svc, engine, _ = await _svc(tmp_path)
    try:
        u = await svc.register("alice@example.com", "hunter2", "Alice")
        assert u.email == "alice@example.com" and u.password_hash
        assert await svc.authenticate("alice@example.com", "hunter2") is not None
        assert await svc.authenticate("alice@example.com", "nope") is None
        with pytest.raises(ValueError):
            await svc.register("alice@example.com", "again1", "Dup")

        p = await svc.create_project(u.id, "My Project")
        assert p.owner_id == u.id
        assert [x.id for x in await svc.list_projects(u.id)] == [p.id]
    finally:
        await engine.dispose()


async def test_google_upsert_links_existing_email(tmp_path):
    svc, engine, _ = await _svc(tmp_path)
    try:
        u = await svc.register("bob@example.com", "hunter2", "Bob")
        linked = await svc.upsert_google_user("google-sub-123", "bob@example.com", "Bob G", "pic")
        assert linked.id == u.id  # linked to the existing account, not a new one
        assert linked.google_sub == "google-sub-123" and linked.avatar_url == "pic"
        # a fresh google user creates a new account
        fresh = await svc.upsert_google_user("sub-999", "carol@example.com", "Carol", None)
        assert fresh.id != u.id and fresh.email == "carol@example.com"
    finally:
        await engine.dispose()


async def test_sync_under_project(tmp_path, monkeypatch):
    svc, engine, producer = await _svc(tmp_path)
    try:
        user = await svc.register("alice@example.com", "hunter2", "Alice")
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
        assert await svc.sync(src.id) == 1
        assert producer.sent[0][1].id == ev.id
        assert len(await svc.list_events(proj.id)) == 1
    finally:
        await engine.dispose()


async def test_oauth_token_reuse(tmp_path):
    svc, engine, _ = await _svc(tmp_path)
    try:
        user = await svc.register("alice@example.com", "hunter2", "Alice")
        proj = await svc.create_project(user.id, "P")
        await svc.set_github_token(proj.id, "alice", "ghp_secret")
        src = await svc.create_source(proj.id, "github", {"repo": "a/b"}, None)
        assert src.secret == "ghp_secret"
    finally:
        await engine.dispose()


def test_oauth_state():
    s = oauth.new_state("proj1", "github")
    assert oauth.consume_state(s) == ("proj1", "github")
    assert oauth.consume_state(s) is None
    g = oauth.new_state("", "google")
    assert oauth.consume_state(g) == ("", "google")


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
    assert all(e.mgtenant == "p1" for e in res.events)


class _FakeConnector:
    kind = "github"

    def __init__(self, events, cursor):
        self._events = events
        self._cursor = cursor

    async def fetch(self, *, org_id, config, secret, since):
        return FetchResult(events=self._events, cursor=self._cursor)
