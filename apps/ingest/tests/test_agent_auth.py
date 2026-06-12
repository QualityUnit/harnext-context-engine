"""Agent harness OAuth: access/refresh tokens + the device-authorization flow."""

from meaninggrid_ingest.security import create_token, decode_token
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings
from meaninggrid_shared import (
    create_agent_access_token,
    decode_agent_access_token,
    hash_refresh_token,
    init_db,
    make_engine,
    make_sessionmaker,
    new_refresh_token,
)


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, event):
        self.sent.append((topic, event))


async def _svc(tmp_path, **overrides):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    settings = IngestSettings(**overrides)
    return SourceService(make_sessionmaker(engine), FakeProducer(), settings), engine


# -- token primitives ------------------------------------------------------


def test_access_token_roundtrip_and_scope():
    tok = create_agent_access_token("org-1", "user-1", "secret", 3600)
    assert decode_agent_access_token(tok, "secret") == {"org": "org-1", "sub": "user-1"}
    assert decode_agent_access_token(tok, "other-secret") is None
    assert decode_agent_access_token("garbage", "secret") is None
    # an agent token must NOT pass as a user session token, and vice-versa
    session = create_token("user-1", "secret", 1)
    assert decode_agent_access_token(session, "secret") is None
    assert decode_token(tok, "secret") is None


def test_access_token_expiry():
    tok = create_agent_access_token("org-1", "user-1", "secret", -1)  # already expired
    assert decode_agent_access_token(tok, "secret") is None


def test_refresh_token_hashing():
    plain, h = new_refresh_token()
    assert hash_refresh_token(plain) == h
    plain2, h2 = new_refresh_token()
    assert plain != plain2 and h != h2  # unique per mint


# -- device flow -----------------------------------------------------------


async def test_device_flow_happy_path(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        req = await svc.create_device_request("harnext-cli")
        # before approval: polling is pending
        outcome, tokens = await svc.poll_device(req.device_code)
        assert outcome == "authorization_pending" and tokens is None

        assert await svc.approve_device(req.user_code, "org-9", "user-9") == "approved"

        outcome, tokens = await svc.poll_device(req.device_code)
        assert outcome == "approved" and tokens is not None
        access, refresh = tokens
        assert decode_agent_access_token(access, svc.s.jwt_secret) == {
            "org": "org-9",
            "sub": "user-9",
        }
        # the device request is consumed: a second poll no longer issues tokens
        outcome, tokens = await svc.poll_device(req.device_code)
        assert outcome == "expired_token" and tokens is None
    finally:
        await engine.dispose()


async def test_device_flow_slow_down(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        req = await svc.create_device_request("harnext-cli")
        first, _ = await svc.poll_device(req.device_code)
        second, _ = await svc.poll_device(req.device_code)  # immediately again
        assert first == "authorization_pending"
        assert second == "slow_down"  # polled inside the interval
    finally:
        await engine.dispose()


async def test_device_flow_denied(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        req = await svc.create_device_request("harnext-cli")
        assert await svc.deny_device(req.user_code) == "denied"
        outcome, tokens = await svc.poll_device(req.device_code)
        assert outcome == "access_denied" and tokens is None
    finally:
        await engine.dispose()


async def test_device_flow_expired(tmp_path):
    # zero TTL → the code is born expired
    svc, engine = await _svc(tmp_path, device_code_ttl_seconds=0)
    try:
        req = await svc.create_device_request("harnext-cli")
        outcome, _ = await svc.poll_device(req.device_code)
        assert outcome == "expired_token"
        # approving an expired code fails
        assert await svc.approve_device(req.user_code, "org-1", "user-1") == "expired"
    finally:
        await engine.dispose()


async def test_unknown_device_code(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        outcome, tokens = await svc.poll_device("does-not-exist")
        assert outcome == "expired_token" and tokens is None
    finally:
        await engine.dispose()


# -- refresh rotation + reuse detection ------------------------------------


async def test_refresh_rotation_and_reuse_detection(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        _, refresh1 = await svc.issue_tokens("org-1", "user-1", "harnext-cli")

        rotated = await svc.rotate_refresh(refresh1, "harnext-cli")
        assert rotated is not None
        access2, refresh2 = rotated
        assert decode_agent_access_token(access2, svc.s.jwt_secret)["org"] == "org-1"
        assert refresh2 != refresh1

        # the old token is now revoked — rotating it again fails …
        assert await svc.rotate_refresh(refresh1, "harnext-cli") is None
        # … and reuse detection burned the chain: the successor is revoked too
        assert await svc.rotate_refresh(refresh2, "harnext-cli") is None
    finally:
        await engine.dispose()


async def test_refresh_wrong_client_rejected(tmp_path):
    svc, engine = await _svc(tmp_path)
    try:
        _, refresh = await svc.issue_tokens("org-1", "user-1", "harnext-cli")
        assert await svc.rotate_refresh(refresh, "someone-else") is None
        assert await svc.rotate_refresh("not-a-real-token", "harnext-cli") is None
    finally:
        await engine.dispose()


async def test_token_tenancy_isolation(tmp_path):
    """A token minted for org A only ever resolves to org A."""
    svc, engine = await _svc(tmp_path)
    try:
        access_a, _ = await svc.issue_tokens("org-A", "user-1", "harnext-cli")
        access_b, _ = await svc.issue_tokens("org-B", "user-2", "harnext-cli")
        assert decode_agent_access_token(access_a, svc.s.jwt_secret)["org"] == "org-A"
        assert decode_agent_access_token(access_b, svc.s.jwt_secret)["org"] == "org-B"
    finally:
        await engine.dispose()
