"""End-to-end route test of the device flow + pushed-conversation ingest.

Exercises the FastAPI app directly (ASGI transport, no lifespan/Kafka) with the
``service``/``settings`` providers overridden to a temp-DB SourceService.
"""

import httpx
import pytest
from httpx import ASGITransport
from meaninggrid_ingest.main import app, service, settings
from meaninggrid_ingest.security import create_token
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings
from meaninggrid_shared import init_db, make_engine, make_sessionmaker

_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class FakeProducer:
    async def send_event(self, topic, event):
        pass


@pytest.fixture
async def ctx(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    svc = SourceService(make_sessionmaker(engine), FakeProducer(), IngestSettings())
    app.dependency_overrides[service] = lambda: svc
    app.dependency_overrides[settings] = lambda: svc.s
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, svc
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_device_code_rejects_unknown_client(ctx):
    client, _ = ctx
    r = await client.post("/oauth/device/code", data={"client_id": "rogue"})
    assert r.status_code == 401 and r.json()["error"] == "invalid_client"


async def test_full_device_flow_and_ingest(ctx):
    client, svc = ctx
    user = await svc.register("dev@example.com", "hunter2", "Dev")
    project = await svc.create_project(user.id, "P1")
    user_bearer = {"Authorization": f"Bearer {create_token(user.id, svc.s.jwt_secret, 1)}"}

    # 1. CLI starts the device flow
    r = await client.post("/oauth/device/code", data={"client_id": "harnext-cli"})
    assert r.status_code == 200
    dc = r.json()
    assert dc["verification_uri"].endswith("/device")
    assert dc["user_code"] in dc["verification_uri_complete"]

    token_form = {
        "grant_type": _DEVICE_GRANT,
        "device_code": dc["device_code"],
        "client_id": "harnext-cli",
    }

    # 2. polling before approval → authorization_pending (RFC error body)
    r = await client.post("/oauth/token", data=token_form)
    assert r.status_code == 400 and r.json()["error"] == "authorization_pending"

    # 3. dashboard: look up + approve against the project
    r = await client.get(
        "/oauth/device/lookup", params={"user_code": dc["user_code"]}, headers=user_bearer
    )
    assert r.status_code == 200 and r.json()["client_id"] == "harnext-cli"
    r = await client.post(
        "/oauth/device/approve",
        json={"user_code": dc["user_code"], "project_id": project.id},
        headers=user_bearer,
    )
    assert r.status_code == 200

    # 4. CLI exchanges for tokens
    r = await client.post("/oauth/token", data=token_form)
    assert r.status_code == 200
    tok = r.json()
    assert tok["token_type"] == "Bearer" and tok["scope"] == "agent"
    agent_bearer = {"Authorization": f"Bearer {tok['access_token']}"}

    # 5. push a conversation: open → append → finalize
    r = await client.post(
        "/agent/sessions",
        json={"client_session_id": "sess-1", "harness": "harnext", "model": "opus"},
        headers=agent_bearer,
    )
    assert r.status_code == 200
    sid = r.json()["id"]

    r = await client.post(
        f"/agent/sessions/{sid}/events",
        json={
            "events": [
                {"seq": 0, "type": "system", "payload": {"k": "v"}},
                {"seq": 1, "type": "assistant", "payload": {"text": "hi"}},
            ]
        },
        headers=agent_bearer,
    )
    assert r.status_code == 200 and r.json()["accepted"] == 2

    r = await client.post(
        f"/agent/sessions/{sid}/finalize",
        json={"stop_reason": "completed", "usage": {"output_tokens": 3}},
        headers=agent_bearer,
    )
    assert r.status_code == 200 and r.json()["status"] == "closed"

    # appending after finalize is rejected
    r = await client.post(
        f"/agent/sessions/{sid}/events",
        json={"events": [{"seq": 2, "type": "result", "payload": {}}]},
        headers=agent_bearer,
    )
    assert r.status_code == 409

    # 6. dashboard reads the conversation back
    r = await client.get(f"/projects/{project.id}/agent-sessions", headers=user_bearer)
    assert r.status_code == 200 and len(r.json()) == 1
    r = await client.get(f"/projects/{project.id}/agent-sessions/{sid}", headers=user_bearer)
    assert r.status_code == 200
    detail = r.json()
    assert [e["seq"] for e in detail["events"]] == [0, 1]

    # 7. refresh rotation + reuse detection
    refresh_form = {
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
        "client_id": "harnext-cli",
    }
    r = await client.post("/oauth/token", data=refresh_form)
    assert r.status_code == 200
    new_refresh = r.json()["refresh_token"]
    assert new_refresh != tok["refresh_token"]
    # reusing the old refresh token now fails
    r = await client.post("/oauth/token", data=refresh_form)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


async def test_token_unsupported_grant(ctx):
    client, _ = ctx
    r = await client.post(
        "/oauth/token", data={"grant_type": "password", "client_id": "harnext-cli"}
    )
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"


async def test_ingest_requires_agent_token(ctx):
    client, _ = ctx
    r = await client.post("/agent/sessions", json={"client_session_id": "x", "harness": "harnext"})
    assert r.status_code == 401


async def test_ingest_tenant_isolation(ctx):
    """An agent token for org A cannot touch a session owned by org B."""
    client, svc = ctx
    a_access, _ = await svc.issue_tokens("org-A", "u", "harnext-cli")
    # a project must exist for the token's org to pass current_agent's check
    ua = await svc.register("a@x.com", "pw1", "A")
    pa = await svc.create_project(ua.id, "A")
    a_access, _ = await svc.issue_tokens(pa.id, ua.id, "harnext-cli")

    ub = await svc.register("b@x.com", "pw2", "B")
    pb = await svc.create_project(ub.id, "B")
    sess = await svc.open_agent_session(pb.id, "cs-b", "harnext", None, None, None)

    r = await client.post(
        f"/agent/sessions/{sess.id}/events",
        json={"events": [{"seq": 0, "type": "assistant", "payload": {}}]},
        headers={"Authorization": f"Bearer {a_access}"},
    )
    assert r.status_code == 404  # org A can't see org B's session
