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


def test_mcp_token_roundtrip():
    from meaninggrid_shared import create_mcp_token, decode_mcp_token

    tok = create_mcp_token("org-xyz", "s3cret")
    assert decode_mcp_token(tok, "s3cret") == "org-xyz"
    assert decode_mcp_token(tok, "wrong-secret") is None
    assert decode_mcp_token("garbage", "s3cret") is None
    assert create_mcp_token("org-xyz", "s3cret") == tok  # deterministic / stable
    # a user session token (no mcp scope) must NOT pass as an MCP token, and vice versa
    session = create_token("user-1", "s3cret", 1)
    assert decode_mcp_token(session, "s3cret") is None
    assert decode_token(tok, "s3cret") is None


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


async def test_delete_project_cascades(tmp_path, monkeypatch):
    """A project with a source + ingested events must delete cleanly. The
    sources->projects FK (under PRAGMA foreign_keys=ON) means the project row
    can only go once its children are removed first."""
    svc, engine, _ = await _svc(tmp_path)
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
        await svc.sync(src.id)
        assert len(await svc.list_events(proj.id)) == 1

        assert await svc.delete_project(proj.id) is True
        assert await svc.get_project(proj.id) is None
        assert await svc.list_sources(proj.id) == []
        assert await svc.list_events(proj.id) == []
        # deleting a project that no longer exists is a no-op, not an error
        assert await svc.delete_project(proj.id) is False
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


def test_slack_signature_verify():
    import hashlib
    import hmac
    import time as _t

    from meaninggrid_ingest.security import verify_slack_signature

    secret, body = "shh", '{"x":1}'
    ts = str(int(_t.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    assert verify_slack_signature(secret, ts, sig, body)
    assert not verify_slack_signature(secret, ts, "v0=deadbeef", body)  # wrong sig
    assert not verify_slack_signature(secret, str(int(_t.time()) - 9999), sig, body)  # replay
    assert not verify_slack_signature("", ts, sig, body)  # unconfigured


async def test_slack_event_routing(tmp_path):
    svc, engine, producer = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        await svc.set_slack_token(p.id, "T1", "Team", "xoxb")
        await svc.create_source(p.id, "slack", {"channel_id": "C1", "channel_name": "eng"}, "xoxb")
        ev = {"type": "message", "channel": "C1", "user": "U1", "text": "hi", "ts": "1700000000.0001"}
        assert await svc.ingest_slack_event("T1", ev) == 1
        sent = producer.sent[-1][1]
        assert sent.id == "slack-C1-1700000000.0001" and sent.subject == "channel:eng"
        assert await svc.ingest_slack_event("T1", {**ev, "channel": "CX"}) == 0  # unregistered channel
        assert await svc.ingest_slack_event("OTHER", ev) == 0  # wrong workspace
    finally:
        await engine.dispose()


async def test_slack_webhook_endpoint(tmp_path):
    import hashlib
    import hmac
    import json as _json
    import time as _t

    import httpx
    from meaninggrid_ingest.main import app
    from meaninggrid_ingest.main import service as service_dep
    from meaninggrid_ingest.main import settings as settings_dep

    svc, engine, producer = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        await svc.set_slack_token(p.id, "T1", "Team", "xoxb")
        await svc.create_source(p.id, "slack", {"channel_id": "C1", "channel_name": "eng"}, "xoxb")

        cfg = IngestSettings(slack_signing_secret="shh")
        app.dependency_overrides[service_dep] = lambda: svc
        app.dependency_overrides[settings_dep] = lambda: cfg

        def sign(body: str) -> dict[str, str]:
            ts = str(int(_t.time()))
            sig = "v0=" + hmac.new(b"shh", f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
            return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig}

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            body = _json.dumps({"type": "url_verification", "challenge": "abc123"})
            r = await c.post("/webhooks/slack", content=body, headers=sign(body))
            assert r.status_code == 200 and r.json()["challenge"] == "abc123"

            body = _json.dumps(
                {
                    "type": "event_callback",
                    "team_id": "T1",
                    "event": {
                        "type": "message",
                        "channel": "C1",
                        "user": "U1",
                        "text": "hello",
                        "ts": "1700000001.0002",
                    },
                }
            )
            r = await c.post("/webhooks/slack", content=body, headers=sign(body))
            assert r.status_code == 200
            assert any(e.id == "slack-C1-1700000001.0002" for _, e in producer.sent)

            r = await c.post(
                "/webhooks/slack",
                content=body,
                headers={"X-Slack-Request-Timestamp": str(int(_t.time())), "X-Slack-Signature": "v0=bad"},
            )
            assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_oauth_state():
    s = oauth.new_state("proj1", "github")
    assert oauth.consume_state(s) == ("proj1", "github")
    assert oauth.consume_state(s) is None
    g = oauth.new_state("", "google")
    assert oauth.consume_state(g) == ("", "google")


def test_github_normalize_repo():
    from meaninggrid_ingest.connectors.github import normalize_repo

    cases = {
        "QualityUnit/pyworkflow": "QualityUnit/pyworkflow",
        "https://github.com/QualityUnit/pyworkflow": "QualityUnit/pyworkflow",
        "https://github.com/QualityUnit/pyworkflow.git": "QualityUnit/pyworkflow",
        "http://github.com/QualityUnit/pyworkflow/": "QualityUnit/pyworkflow",
        "github.com/QualityUnit/pyworkflow": "QualityUnit/pyworkflow",
        "git@github.com:QualityUnit/pyworkflow.git": "QualityUnit/pyworkflow",
        "https://github.com/QualityUnit/pyworkflow/tree/main": "QualityUnit/pyworkflow",
        "  QualityUnit/pyworkflow  ": "QualityUnit/pyworkflow",
    }
    for raw, want in cases.items():
        assert normalize_repo(raw) == want, raw


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
