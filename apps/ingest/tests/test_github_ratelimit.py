"""Rate-limit handling: connectors raise ``RateLimitedError`` (carrying the API's
reset time), the poll task backs off and retries, and a rate-limited sync leaves
the source ``active`` rather than flipping it to a permanent error."""

import httpx
import pytest
from meaninggrid_ingest.connectors import github
from meaninggrid_ingest.connectors.base import RateLimitedError, parse_retry_after
from meaninggrid_ingest.connectors.github import (
    GitHubConnector,
    _github_retry_after,
    _is_github_rate_limited,
)
from meaninggrid_ingest.service import SourceService
from meaninggrid_ingest.settings import IngestSettings
from meaninggrid_ingest.tasks import _poll_backoff_seconds
from meaninggrid_shared import init_db, make_engine, make_sessionmaker, utcnow


# -- parse_retry_after ------------------------------------------------------
def test_parse_retry_after_delta_seconds():
    assert parse_retry_after({"Retry-After": "120"}) == 120.0


def test_parse_retry_after_fractional():  # Discord sends fractional seconds
    assert parse_retry_after({"Retry-After": "1.5"}) == 1.5


def test_parse_retry_after_http_date():
    raw = "Wed, 21 Oct 2099 07:28:00 GMT"  # far future → positive, large
    secs = parse_retry_after({"Retry-After": raw})
    assert secs is not None and secs > 0


def test_parse_retry_after_absent_or_garbage():
    assert parse_retry_after({}) is None
    assert parse_retry_after({"Retry-After": "soon"}) is None


# -- GitHub detection + reset time ------------------------------------------
def _resp(status, headers=None, text=""):
    return httpx.Response(status_code=status, headers=headers or {}, text=text)


def test_primary_limit_uses_ratelimit_reset():
    reset = int(utcnow().timestamp()) + 100
    r = _resp(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)})
    assert _is_github_rate_limited(r)
    secs = _github_retry_after(r)
    assert secs is not None and 90 <= secs <= 100


def test_secondary_limit_uses_retry_after():
    r = _resp(403, {"Retry-After": "30"}, text="You have exceeded a secondary rate limit")
    assert _is_github_rate_limited(r)
    assert _github_retry_after(r) == 30.0


def test_retry_after_header_wins_over_reset():
    reset = int(utcnow().timestamp()) + 999
    r = _resp(
        429, {"Retry-After": "5", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)}
    )
    assert _github_retry_after(r) == 5.0


def test_permission_403_is_not_rate_limited():
    r = _resp(403, text="Resource not accessible by integration")
    assert not _is_github_rate_limited(r)


# -- the connector raises RateLimitedError on a limited response -----------------
class _FakeClient:
    def __init__(self, response):
        self._response = response

    async def get(self, url, params=None):
        return self._response


async def test_get_raises_ratelimited_with_reset():
    reset = int(utcnow().timestamp()) + 60
    client = _FakeClient(
        _resp(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)})
    )
    with pytest.raises(RateLimitedError) as ei:
        await GitHubConnector()._get(client, f"{github._API}/repos/a/b/issues", None)
    assert ei.value.provider == "GitHub"
    assert ei.value.retry_after is not None and ei.value.retry_after > 0


async def test_get_permission_403_still_raises_runtimeerror():
    client = _FakeClient(_resp(403, text="Resource not accessible by integration"))
    with pytest.raises(RuntimeError) as ei:
        await GitHubConnector()._get(client, f"{github._API}/repos/a/b/issues", None)
    assert not isinstance(ei.value, RateLimitedError)


# -- the poll task's backoff ------------------------------------------------
def test_backoff_honours_retry_after():
    exc = RateLimitedError("GitHub", retry_after=42.0)
    assert _poll_backoff_seconds(0, exc) == 43.0  # +1s slack past the window


def test_backoff_exponential_when_no_hint():
    exc = RateLimitedError("GitHub", retry_after=None)
    assert _poll_backoff_seconds(0, exc) == 60.0
    assert _poll_backoff_seconds(1, exc) == 120.0
    assert _poll_backoff_seconds(10, exc) == 3600.0  # capped at 1h


# -- sync() treats RateLimitedError as transient (no permanent error) ------------
class _FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_event(self, topic, event):  # pragma: no cover - never reached here
        self.sent.append((topic, event))


class _LimitedConnector:
    async def fetch(self, *, org_id, config, secret, since):
        raise RateLimitedError("GitHub", retry_after=30.0)


async def test_sync_ratelimited_keeps_source_active(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/meta.sqlite")
    await init_db(engine)
    svc = SourceService(make_sessionmaker(engine), _FakeProducer(), IngestSettings())
    try:
        u = await svc.register("a@b.com", "hunter2", "A")
        p = await svc.create_project(u.id, "P")
        src = await svc.create_source(p.id, "github", {"repo": "a/b"}, "tok")

        monkeypatch.setattr(
            "meaninggrid_ingest.service.get_connector", lambda kind, **kw: _LimitedConnector()
        )
        with pytest.raises(RateLimitedError):
            await svc.sync(src.id)

        refreshed = await svc.get_source(src.id)
        assert refreshed.status == "active"  # NOT "error" — transient back-off
        assert refreshed.last_error is None
    finally:
        await engine.dispose()
