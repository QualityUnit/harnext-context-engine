"""Ingest: connectors, auth (register/login/Google), projects, sync, OAuth."""

from datetime import UTC, datetime

import pytest
from harnext_ingest import oauth
from harnext_ingest.connectors.base import FetchResult
from harnext_ingest.connectors.github import GitHubConnector
from harnext_ingest.security import create_token, decode_token, hash_password, verify_password
from harnext_ingest.service import SourceService
from harnext_ingest.settings import IngestSettings
from harnext_shared import CloudEvent, init_db, make_engine, make_sessionmaker


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
    from harnext_shared import create_mcp_token, decode_mcp_token

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
            "harnext_ingest.service.get_connector",
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
            "harnext_ingest.service.get_connector",
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


async def test_mcp_request_analytics_and_list(tmp_path):
    """MCP request rows feed the dashboard: a newest-first list + a per-day /
    per-tool / error aggregate, scoped to the project and cleaned up on delete."""
    from harnext_shared import McpRequest

    svc, engine, _ = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        other = await svc.create_project(u.id, "Other")

        async with svc.sm() as s:
            s.add_all(
                [
                    McpRequest(id="r1", org_id=p.id, tool="context_research",
                               params_json='{"question":"q"}', status="ok",
                               response_json='{"answer":"a"}', error=None, duration_ms=120),
                    McpRequest(id="r2", org_id=p.id, tool="context_update",
                               params_json='{"instruction":"i"}', status="error",
                               response_json=None, error="boom", duration_ms=80),
                    # a different project's row must not leak into P's view
                    McpRequest(id="r3", org_id=other.id, tool="context_research",
                               params_json="{}", status="ok", response_json="{}",
                               error=None, duration_ms=10),
                ]
            )
            await s.commit()

        rows = await svc.list_mcp_requests(p.id)
        assert [r.id for r in rows] == ["r2", "r1"]  # newest first (r2 created after r1)

        stats = await svc.mcp_analytics(p.id, days=14)
        assert stats["total_requests"] == 2
        assert stats["total_errors"] == 1
        assert stats["avg_duration_ms"] == 100  # (120 + 80) / 2
        assert stats["by_tool"] == {"context_research": 1, "context_update": 1}
        assert len(stats["requests_per_day"]) == 14
        assert sum(stats["requests_per_day"]) == 2  # both landed today
        assert stats["requests_per_day"][-1] == 2

        # the other project sees only its own row
        assert (await svc.mcp_analytics(other.id))["total_requests"] == 1

        # deleting the project removes its MCP rows
        assert await svc.delete_project(p.id) is True
        assert await svc.list_mcp_requests(p.id) == []
    finally:
        await engine.dispose()


async def test_mcp_requests_endpoint(tmp_path):
    """The owned-project guard + JSON round-trip on the two MCP-activity routes."""
    import httpx
    from harnext_ingest.main import app
    from harnext_ingest.main import current_user as user_dep
    from harnext_ingest.main import service as service_dep
    from harnext_shared import McpRequest

    svc, engine, _ = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        async with svc.sm() as s:
            s.add(
                McpRequest(id="r1", org_id=p.id, tool="context_get_urls",
                           params_json='{"urls":["cms://conversation/x"]}', status="ok",
                           response_json='[{"found":true}]', error=None, duration_ms=42)
            )
            await s.commit()

        app.dependency_overrides[service_dep] = lambda: svc
        app.dependency_overrides[user_dep] = lambda: u

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get(f"/projects/{p.id}/mcp-requests")
            assert r.status_code == 200
            body = r.json()
            assert len(body) == 1
            assert body[0]["tool"] == "context_get_urls"
            assert body[0]["params"] == {"urls": ["cms://conversation/x"]}  # parsed back to JSON
            assert body[0]["response"] == [{"found": True}]
            assert body[0]["duration_ms"] == 42

            r = await c.get(f"/projects/{p.id}/mcp-requests/stats")
            assert r.status_code == 200
            assert r.json()["total_requests"] == 1
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_beta_signup_tags_mailchimp(monkeypatch):
    import httpx
    from harnext_ingest import mailchimp
    from harnext_ingest.main import app
    from harnext_ingest.main import settings as settings_dep

    calls: list[dict] = []

    async def fake_upsert(**kw):
        calls.append(kw)
        return "subscribed"

    monkeypatch.setattr(mailchimp, "upsert_member", fake_upsert)
    cfg = IngestSettings(
        mailchimp_api_key="key-us21", mailchimp_audience_id="485db66a95",
        mailchimp_beta_tag="harnext-closed-beta",
    )
    app.dependency_overrides[settings_dep] = lambda: cfg
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/beta/signup", json={"email": "Ada@Acme.io", "name": "Ada Lovelace"})
            assert r.status_code == 200
            assert r.json() == {"ok": True, "status": "subscribed"}
            assert calls[0]["email"] == "ada@acme.io"  # normalised
            assert calls[0]["audience_id"] == "485db66a95"
            assert calls[0]["tag"] == "harnext-closed-beta"

            bad = await c.post("/beta/signup", json={"email": "not-an-email"})
            assert bad.status_code == 400
    finally:
        app.dependency_overrides.clear()


async def test_beta_signup_503_without_key(monkeypatch):
    import httpx
    from harnext_ingest.main import app
    from harnext_ingest.main import settings as settings_dep

    app.dependency_overrides[settings_dep] = lambda: IngestSettings(mailchimp_api_key=None)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/beta/signup", json={"email": "a@b.com", "name": "A"})
            assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


async def test_github_login_captures_beta_lead(tmp_path, monkeypatch):
    import httpx
    from harnext_ingest import mailchimp, oauth
    from harnext_ingest.main import app
    from harnext_ingest.main import service as service_dep
    from harnext_ingest.main import settings as settings_dep

    svc, engine, _ = await _svc(tmp_path)
    captured: list[dict] = []

    async def fake_exchange(*a, **k):
        return {"email": "lead@acme.io", "name": "Lead Person", "avatar": None}

    async def fake_upsert(**kw):
        captured.append(kw)
        return "subscribed"

    monkeypatch.setattr(oauth, "github_login_exchange", fake_exchange)
    monkeypatch.setattr(mailchimp, "upsert_member", fake_upsert)

    cfg = IngestSettings(
        github_oauth_client_id="cid", github_oauth_client_secret="sec",
        github_beta_capture=True, mailchimp_api_key="key-us3",
        mailchimp_audience_id="485db66a95", mailchimp_beta_tag="harnext-closed-beta",
        web_origin="https://app.harnext.dev",
    )
    app.dependency_overrides[service_dep] = lambda: svc
    app.dependency_overrides[settings_dep] = lambda: cfg
    try:
        state = oauth.new_state("", "github_login")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get(f"/auth/github/callback?code=abc&state={state}")
            # Funnels to the newsletter page — no session token in the redirect.
            assert r.status_code in (302, 307)
            assert r.headers["location"] == "https://app.harnext.dev/register?joined=1"
        # Lead tagged in the right audience; NO dashboard account was created.
        assert captured[0]["email"] == "lead@acme.io"
        assert captured[0]["audience_id"] == "485db66a95"
        assert captured[0]["tag"] == "harnext-closed-beta"
        assert await svc.authenticate("lead@acme.io", "") is None
    finally:
        app.dependency_overrides.clear()
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

    from harnext_ingest.security import verify_slack_signature

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
    from harnext_ingest.main import app
    from harnext_ingest.main import service as service_dep
    from harnext_ingest.main import settings as settings_dep

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


def test_github_signature_verify():
    import hashlib
    import hmac

    from harnext_ingest.security import verify_github_signature

    secret, body = "ghsecret", b'{"zen":"hi"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(secret, sig, body)
    assert not verify_github_signature(secret, "sha256=bad", body)
    assert not verify_github_signature("", sig, body)


async def test_github_event_routing(tmp_path, monkeypatch):
    # stub changed-file enrichment so the routing test stays offline + deterministic
    async def _noop(client, repo, ev_type, data):
        return None

    monkeypatch.setattr("harnext_ingest.connectors.github.enrich_files", _noop)
    svc, engine, producer = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        await svc.create_source(p.id, "github", {"repo": "acme/web"}, None)

        push = {
            "ref": "refs/heads/main",
            "repository": {"full_name": "acme/web", "default_branch": "main"},
            "commits": [
                {"id": "abc", "message": "fix", "timestamp": "2026-06-08T00:00:00Z",
                 "url": "u", "author": {"name": "ada"}}
            ],
        }
        assert await svc.ingest_github_event("push", push) == 1
        assert producer.sent[-1][1].id == "github-commit-acme/web-abc"
        assert producer.sent[-1][1].type == "com.github.commit"

        # non-default branch -> ignored
        assert await svc.ingest_github_event("push", {**push, "ref": "refs/heads/feat"}) == 0
        # different repo -> no matching source
        assert await svc.ingest_github_event("push", {**push, "repository": {"full_name": "x/y", "default_branch": "main"}}) == 0

        pr = {
            "action": "opened",
            "repository": {"full_name": "acme/web"},
            "pull_request": {"number": 9, "title": "PR", "state": "open", "body": "y",
                             "labels": [], "user": {"login": "bob"}, "html_url": "u",
                             "updated_at": "2026-06-08T02:00:00Z"},
        }
        assert await svc.ingest_github_event("pull_request", pr) == 1
        assert producer.sent[-1][1].type == "com.github.pull_request"
        assert producer.sent[-1][1].data["is_pull_request"] is True
    finally:
        await engine.dispose()


async def test_github_webhook_endpoint(tmp_path, monkeypatch):
    import hashlib
    import hmac
    import json as _json

    async def _noop(client, repo, ev_type, data):
        return None

    monkeypatch.setattr("harnext_ingest.connectors.github.enrich_files", _noop)

    import httpx
    from harnext_ingest.main import app
    from harnext_ingest.main import service as service_dep
    from harnext_ingest.main import settings as settings_dep

    svc, engine, producer = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        await svc.create_source(p.id, "github", {"repo": "acme/web"}, None)

        cfg = IngestSettings(github_webhook_secret="ghsecret")
        app.dependency_overrides[service_dep] = lambda: svc
        app.dependency_overrides[settings_dep] = lambda: cfg

        def sign(raw: bytes) -> str:
            return "sha256=" + hmac.new(b"ghsecret", raw, hashlib.sha256).hexdigest()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            # ping handshake
            raw = _json.dumps({"zen": "Keep it simple"}).encode()
            r = await c.post("/webhooks/github", content=raw,
                             headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": sign(raw)})
            assert r.status_code == 200

            # signed push -> a commit CloudEvent is produced
            raw = _json.dumps({
                "ref": "refs/heads/main",
                "repository": {"full_name": "acme/web", "default_branch": "main"},
                "commits": [{"id": "deadbeef", "message": "x", "timestamp": "2026-06-08T00:00:00Z",
                             "url": "u", "author": {"name": "ada"}}],
            }).encode()
            r = await c.post("/webhooks/github", content=raw,
                             headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": sign(raw)})
            assert r.status_code == 200
            assert any(e.id == "github-commit-acme/web-deadbeef" for _, e in producer.sent)

            # bad signature -> 401
            r = await c.post("/webhooks/github", content=raw,
                             headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=bad"})
            assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_github_source_autoregisters_webhook(tmp_path, monkeypatch):
    svc, engine, _ = await _svc(tmp_path)
    try:
        svc.s = IngestSettings(github_webhook_secret="ghsecret", oauth_redirect_base="https://x.dev/api")
        calls = []

        async def fake_create(token, repo, url, secret):
            calls.append((token, repo, url, secret))
            return "hook-1"

        monkeypatch.setattr("harnext_ingest.oauth.github_create_webhook", fake_create)

        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        await svc.set_github_token(p.id, "alice", "ghp_oauth")
        # a pasted URL is normalized to owner/name for the API call
        await svc.create_source(p.id, "github", {"repo": "https://github.com/acme/web"}, None)
        assert calls == [("ghp_oauth", "acme/web", "https://x.dev/api/webhooks/github", "ghsecret")]

        # no server secret -> auto-registration is skipped (polling still works)
        calls.clear()
        svc.s = IngestSettings(github_webhook_secret=None)
        await svc.create_source(p.id, "github", {"repo": "acme/web2"}, None)
        assert calls == []
    finally:
        await engine.dispose()


def test_oauth_state():
    s = oauth.new_state("proj1", "github")
    assert oauth.consume_state(s) == ("proj1", "github")
    assert oauth.consume_state(s) is None
    g = oauth.new_state("", "google")
    assert oauth.consume_state(g) == ("", "google")


def test_github_normalize_repo():
    from harnext_ingest.connectors.github import normalize_repo

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


# -- connector taxonomy + Discord ------------------------------------------
def test_slack_message_event_shape():
    """The shared chat-message builder must reproduce Slack's exact CloudEvent
    (the id is an IngestedEvent PK — drift would silently double-ingest)."""
    from harnext_ingest.connectors.slack import slack_message_event

    m = {"channel": "C1", "user": "U1", "text": "hi", "ts": "1700000000.0001", "reply_count": 2}
    e = slack_message_event("org1", "C1", "eng", m)
    assert e.id == "slack-C1-1700000000.0001"
    assert e.source == "slack:C1"
    assert e.type == "com.slack.message"
    assert e.subject == "channel:eng"
    assert e.mgtenant == "org1"
    assert e.data == {
        "channel": "C1",
        "channel_name": "eng",
        "text": "hi",
        "user": "U1",
        "ts": "1700000000.0001",
        "reply_count": 2,
    }


def test_event_connector_lookup():
    from harnext_ingest.connectors import event_connector
    from harnext_ingest.connectors.base import EventConnector

    assert isinstance(event_connector("slack"), EventConnector)
    assert isinstance(event_connector("github"), EventConnector)
    assert event_connector("discord") is None  # polling-only — no webhook
    assert event_connector("nope") is None


def test_discord_authorize_url():
    url = oauth.discord_authorize_url("cid", "https://x/api/oauth/discord/callback", "st")
    assert url.startswith("https://discord.com/oauth2/authorize?")
    assert "scope=bot" in url and "permissions=66560" in url
    assert "client_id=cid" in url and "state=st" in url


def test_discord_raise_for_status():
    from harnext_ingest.connectors.discord import DiscordConnector

    class R:
        def __init__(self, code, headers=None):
            self.status_code = code
            self.headers = headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

    for code, frag in [(401, "token"), (403, "permission"), (404, "not found")]:
        with pytest.raises(RuntimeError) as ei:
            DiscordConnector._raise_for_discord(R(code))
        assert frag in str(ei.value)
    with pytest.raises(RuntimeError) as ei:
        DiscordConnector._raise_for_discord(R(429, {"Retry-After": "3"}))
    assert "rate limit" in str(ei.value) and "3" in str(ei.value)
    DiscordConnector._raise_for_discord(R(200))  # ok → no raise


async def test_discord_connector_builds_events(monkeypatch):
    import httpx
    from harnext_ingest.connectors.discord import DiscordConnector

    messages = [  # Discord returns newest-first
        {"id": "30", "content": "third", "timestamp": "2026-06-03T00:00:00+00:00",
         "author": {"username": "carol"}},
        {"id": "20", "content": "second", "timestamp": "2026-06-02T00:00:00+00:00",
         "author": {"username": "bob"}},
        {"id": "10", "content": "first", "timestamp": "2026-06-01T00:00:00+00:00",
         "author": {"username": "alice"}},
    ]

    class FakeResp:
        status_code = 200
        headers: dict = {}

        def json(self):
            return messages

        def raise_for_status(self):
            pass

    captured = {}

    async def fake_get(self, url, params=None, headers=None):
        captured.update(url=url, params=params, headers=headers)
        return FakeResp()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    res = await DiscordConnector().fetch(
        org_id="p1",
        config={"channel_id": "CH1", "channel_name": "general", "guild_id": "G1"},
        secret="bot-token",
        since="5",
    )
    # reversed to chronological (oldest first)
    assert [e.data["content"] for e in res.events] == ["first", "second", "third"]
    assert all(e.mgtenant == "p1" for e in res.events)
    e = res.events[0]
    assert e.id == "discord-CH1-10"
    assert e.source == "discord:G1:CH1"
    assert e.type == "com.discord.message"
    assert e.subject == "channel:general"
    assert e.data["author"] == "alice" and e.data["guild_id"] == "G1"
    assert res.cursor == "30"  # max snowflake (int compare)
    assert captured["headers"]["Authorization"] == "Bot bot-token"
    assert captured["params"]["after"] == "5"  # cursor forwarded


async def test_discord_source_uses_bot_token(tmp_path):
    svc, engine, _ = await _svc(tmp_path)
    try:
        svc.s = IngestSettings(discord_bot_token="bot-xyz")
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        await svc.set_discord_guild(p.id, "G1", "My Guild")
        proj = await svc.get_project(p.id)
        assert proj.discord_guild_id == "G1" and proj.discord_guild_name == "My Guild"
        # no per-source secret → falls back to the app-level bot token; guild stamped in
        src = await svc.create_source(
            p.id, "discord", {"channel_id": "CH1", "channel_name": "gen"}, None
        )
        assert src.secret == "bot-xyz"
        import json as _json

        assert _json.loads(src.config_json)["guild_id"] == "G1"
        # disconnect clears the guild
        await svc.disconnect_provider(p.id, "discord")
        proj = await svc.get_project(p.id)
        assert proj.discord_guild_id is None
    finally:
        await engine.dispose()


# -- YouTube ----------------------------------------------------------------
def test_youtube_channel_url_resolution():
    from harnext_ingest.connectors.youtube import _channel_videos_url

    # a bare channel URL is normalized to the uploads (Videos) tab — extracting
    # the channel root instead returns its tabs (Videos/Shorts/…), not videos
    assert (
        _channel_videos_url({"channel_url": "https://www.youtube.com/@FlowHunt"})
        == "https://www.youtube.com/@FlowHunt/videos"
    )
    assert (
        _channel_videos_url({"channel_url": "https://www.youtube.com/channel/UC123/"})
        == "https://www.youtube.com/channel/UC123/videos"
    )
    # a URL that already targets a tab / playlist / video is left as given
    assert (
        _channel_videos_url({"channel_url": "https://www.youtube.com/@FlowHunt/videos"})
        == "https://www.youtube.com/@FlowHunt/videos"
    )
    assert (
        _channel_videos_url({"channel_url": "https://www.youtube.com/playlist?list=PL1"})
        == "https://www.youtube.com/playlist?list=PL1"
    )
    # channel_id forms
    assert (
        _channel_videos_url({"channel_id": "@handle"}) == "https://www.youtube.com/@handle/videos"
    )
    assert (
        _channel_videos_url({"channel_id": "UC123"})
        == "https://www.youtube.com/channel/UC123/videos"
    )
    # a bare identifier is treated as a handle
    assert _channel_videos_url({"channel_id": "bare"}) == "https://www.youtube.com/@bare/videos"


def test_youtube_caption_parsers():
    from harnext_ingest.connectors.youtube import _parse_caption

    json3 = '{"events":[{"segs":[{"utf8":"first "},{"utf8":"clip"}]},{"segs":[]}]}'
    assert _parse_caption(json3, "json3") == "first clip"

    vtt = "WEBVTT\n\n00:00.000 --> 00:02.000\nsecond video\n\n00:02.000 --> 00:04.000\nsecond video\ncaptions here\n"
    assert _parse_caption(vtt, "vtt") == "second video captions here"  # consecutive dup collapsed

    xml = '<?xml version="1.0"?><transcript><text start="0" dur="2">third &amp; final</text><text start="2" dur="2">video</text></transcript>'
    assert _parse_caption(xml, "srv1") == "third & final video"


def test_youtube_track_selection():
    from harnext_ingest.connectors.youtube import _select_track

    info = {
        "subtitles": {
            "en": [{"ext": "json3", "url": "manual-en"}],
            "fr": [{"ext": "vtt"}],
        },
        "automatic_captions": {"en": [{"ext": "json3", "url": "auto-en"}]},
    }
    # preferred lang, manual subtitle wins over the auto-caption
    lang, fmts = _select_track(info, ["en"])
    assert lang == "en" and fmts[0]["url"] == "manual-en"
    # preferred lang only present as an auto-caption → use it
    lang, fmts = _select_track({"automatic_captions": info["automatic_captions"]}, ["en"])
    assert lang == "en" and fmts[0]["url"] == "auto-en"
    # none of the preferred langs exist → fall back to any available track
    lang, fmts = _select_track(info, ["de"])
    assert lang in ("en", "fr")
    # no captions at all
    assert _select_track({}, ["en"]) == (None, None)


class _Caps:
    """Minimal httpx-style response carrying a caption body."""

    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        pass


async def test_youtube_connector_builds_events(monkeypatch):
    import httpx
    from harnext_ingest.connectors.youtube import YouTubeConnector

    # Channel Videos tab is newest-first; each video resolves to its captions.
    listing = {
        "entries": [
            {
                "id": "vid3",
                "url": "https://www.youtube.com/watch?v=vid3",
                "title": "Third",
            },
            {
                "id": "vid2",
                "url": "https://www.youtube.com/watch?v=vid2",
                "title": "Second",
            },
            {
                "id": "vid1",
                "url": "https://www.youtube.com/watch?v=vid1",
                "title": "First",
            },
        ]
    }
    videos = {
        "vid1": {  # manual subtitle, json3
            "title": "First",
            "timestamp": 1717200000,
            "channel": "Chan",
            "webpage_url": "https://youtu.be/vid1",
            "subtitles": {"en": [{"ext": "json3", "url": "cap://vid1"}]},
        },
        "vid2": {  # auto-caption, vtt
            "title": "Second",
            "timestamp": 1717300000,
            "channel": "Chan",
            "automatic_captions": {"en": [{"ext": "vtt", "url": "cap://vid2"}]},
        },
        "vid3": {  # manual subtitle, srv1 xml
            "title": "Third",
            "timestamp": 1717400000,
            "channel": "Chan",
            "subtitles": {"en": [{"ext": "srv1", "url": "cap://vid3"}]},
        },
    }
    caps = {
        "cap://vid1": '{"events":[{"segs":[{"utf8":"first "},{"utf8":"clip"}]}]}',
        "cap://vid2": "WEBVTT\n\n00:00.000 --> 00:02.000\nsecond video\n\n00:02.000 --> 00:04.000\nsecond video\ncaptions here\n",
        "cap://vid3": "<transcript><text>third &amp; final</text><text>video</text></transcript>",
    }
    calls = []

    def fake_extract(url, *, flat, limit=None):
        calls.append((url, flat))
        if flat:
            return listing
        return videos[url.rsplit("=", 1)[-1]]

    async def fake_get(self, url, params=None, headers=None):
        return _Caps(caps[url])

    monkeypatch.setattr("harnext_ingest.connectors.youtube._extract_info", fake_extract)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    res = await YouTubeConnector().fetch(
        org_id="p1",
        config={"channel_id": "UC123", "channel_name": "My Channel"},
        secret=None,
        since=None,
    )

    # chronological (oldest first), captions parsed per format
    assert [e.data["text"] for e in res.events] == [
        "first clip",
        "second video captions here",
        "third & final video",
    ]
    assert all(e.mgtenant == "p1" for e in res.events)
    e = res.events[0]
    assert e.id == "youtube-UC123-vid1"
    assert e.source == "youtube:UC123"
    assert e.type == "com.youtube.caption"
    assert e.subject == "channel:My Channel"
    assert e.data["video_id"] == "vid1" and e.data["caption_lang"] == "en"
    assert e.data["has_caption"] is True and e.data["url"] == "https://youtu.be/vid1"
    assert res.cursor == "vid3"  # newest enumerated upload
    assert calls[0] == ("https://www.youtube.com/channel/UC123/videos", True)


async def test_youtube_cursor_skips_seen(monkeypatch):
    import httpx
    from harnext_ingest.connectors.youtube import YouTubeConnector

    listing = {
        "entries": [
            {"id": "vid3", "url": "https://www.youtube.com/watch?v=vid3"},
            {"id": "vid2", "url": "https://www.youtube.com/watch?v=vid2"},
            {"id": "vid1", "url": "https://www.youtube.com/watch?v=vid1"},
        ]
    }

    def fake_extract(url, *, flat, limit=None):
        if flat:
            return listing
        return {
            "title": "v",
            "timestamp": 1717400000,
            "subtitles": {"en": [{"ext": "json3", "url": "cap://x"}]},
        }

    async def fake_get(self, url, params=None, headers=None):
        return _Caps('{"events":[{"segs":[{"utf8":"hi"}]}]}')

    monkeypatch.setattr("harnext_ingest.connectors.youtube._extract_info", fake_extract)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    # cursor at vid2 → only vid3 is new; watermark still advances to newest (vid3)
    res = await YouTubeConnector().fetch(
        org_id="p1", config={"channel_id": "UC1"}, secret=None, since="vid2"
    )
    assert [e.data["video_id"] for e in res.events] == ["vid3"]
    assert res.cursor == "vid3"


async def test_youtube_video_without_captions(monkeypatch):
    from harnext_ingest.connectors.youtube import YouTubeConnector

    def fake_extract(url, *, flat, limit=None):
        if flat:
            return {"entries": [{"id": "vid1", "url": "https://www.youtube.com/watch?v=vid1"}]}
        return {"title": "No caps", "timestamp": 1717400000}  # no subtitle tracks

    monkeypatch.setattr("harnext_ingest.connectors.youtube._extract_info", fake_extract)
    res = await YouTubeConnector().fetch(
        org_id="p1",
        config={"channel_id": "UC1", "channel_name": "C"},
        secret=None,
        since=None,
    )
    assert len(res.events) == 1
    e = res.events[0]
    assert e.data["has_caption"] is False
    assert e.data["text"] == "" and e.data["caption_lang"] is None


async def test_youtube_derives_channel_key_from_listing(monkeypatch):
    import httpx
    from harnext_ingest.connectors.youtube import YouTubeConnector

    # Source configured with only a /videos URL → the canonical UC id and the
    # display name are taken from what yt-dlp reports for the listing, so the
    # event source/id stay clean instead of embedding the URL.
    listing = {
        "channel_id": "UCstableid",
        "channel": "Stable Name",
        "entries": [{"id": "vidA", "url": "https://www.youtube.com/watch?v=vidA"}],
    }

    def fake_extract(url, *, flat, limit=None):
        if flat:
            return listing
        return {
            "title": "A",
            "timestamp": 1717400000,
            "subtitles": {"en": [{"ext": "json3", "url": "cap://a"}]},
        }

    async def fake_get(self, url, params=None, headers=None):
        return _Caps('{"events":[{"segs":[{"utf8":"hi"}]}]}')

    monkeypatch.setattr("harnext_ingest.connectors.youtube._extract_info", fake_extract)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    res = await YouTubeConnector().fetch(
        org_id="p1",
        config={"channel_url": "https://www.youtube.com/@stable/videos"},
        secret=None,
        since=None,
    )
    e = res.events[0]
    assert e.source == "youtube:UCstableid"
    assert e.id == "youtube-UCstableid-vidA"
    assert e.subject == "channel:Stable Name"


async def test_youtube_source_create_and_registry(tmp_path):
    from harnext_ingest.connectors import SUPPORTED_KINDS, get_connector
    from harnext_ingest.connectors.youtube import YouTubeConnector

    assert "youtube" in SUPPORTED_KINDS
    assert isinstance(get_connector("youtube"), YouTubeConnector)

    svc, engine, _ = await _svc(tmp_path)
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        # YouTube polls public captions — no provider token, so no secret is stored
        src = await svc.create_source(
            p.id, "youtube", {"channel_id": "UC1", "channel_name": "C"}, None
        )
        assert src.kind == "youtube" and src.secret is None
    finally:
        await engine.dispose()
