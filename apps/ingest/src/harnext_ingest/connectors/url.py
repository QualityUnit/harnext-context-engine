"""Single-URL connector — ingest one web page as a source.

A degenerate website source: the user gives one page URL and we fetch *just that
page* into a ``com.web.page`` event — the same shape the sitemap connector emits,
so the classifier and builder treat it identically (and a single URL plus a
sitemap for the same host fold into one ``site:<host>`` entity).

Unlike :mod:`~harnext_ingest.connectors.sitemap` there's no discovery and no
``robots.txt`` check — the user pointed us at this exact page deliberately, so
each poll just re-fetches it. Freshness rides on the page's own ``Last-Modified``
/ ``ETag`` (falling back to a content hash): an unchanged page yields no event,
while a changed one gets a fresh event id so the builder reprocesses it.
"""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlparse

import httpx
from harnext_shared import CloudEvent, utcnow

from harnext_ingest.connectors.base import FetchResult, PollingConnector
from harnext_ingest.connectors.sitemap import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    extract_text,
    extract_title,
)

log = logging.getLogger("ingest.url")


def normalize_url(raw: str) -> str:
    """Prepend ``https://`` when the user pastes a bare host/path (so a stored
    config is always a fetchable absolute URL)."""
    s = raw.strip()
    return s if "://" in s else f"https://{s}"


def _freshness_token(r: httpx.Response, text: str) -> str:
    """A short, comparable change token for the page: prefer the validators the
    origin gives us (``Last-Modified`` / ``ETag``), else hash the readable text.
    Stored as the source cursor so an unchanged page re-poll emits nothing."""
    raw = r.headers.get("Last-Modified") or r.headers.get("ETag")
    if raw:
        return raw.strip()
    return "sha1:" + hashlib.sha1(text.encode()).hexdigest()[:16]  # noqa: S324 — change tag, not security


def page_event(
    *, org_id: str, site: str, url: str, title: str | None, text: str, status: int, token: str
) -> CloudEvent:
    """One fetched page → one ``com.web.page`` event. The id is stable per
    ``(url, token)``: re-fetching an unchanged page dedupes (same id), while a
    page whose ``token`` moved produces a fresh id — mirroring the sitemap
    connector's ``lastmod``-in-id scheme, but keyed on the page's own validators
    since a single URL has no sitemap ``<lastmod>``."""
    key = hashlib.sha1(url.encode()).hexdigest()[:16]  # noqa: S324 — id, not security
    tag = hashlib.sha1(token.encode()).hexdigest()[:12]  # noqa: S324 — id, not security
    return CloudEvent(
        id=f"web-{key}-{tag}",
        source=f"url:{site}",
        type="com.web.page",
        subject=f"site:{site}",
        time=utcnow(),
        mgtenant=org_id,
        data={
            "url": url,
            "site": site,
            "title": title,
            "text": PollingConnector.clip(text),
            "status": status,
        },
    )


class UrlConnector(PollingConnector):
    kind = "url"

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.user_agent = user_agent

    @classmethod
    def from_settings(cls, s) -> UrlConnector:  # noqa: ANN001 — duck-typed IngestSettings
        """Share the deployment's crawl timeout / byte cap / UA with the sitemap
        connector so a single page is fetched as politely as a crawled one."""
        return cls(
            timeout=s.crawl_timeout_seconds,
            max_bytes=s.crawl_max_bytes,
            user_agent=s.crawl_user_agent,
        )

    @staticmethod
    def site_of(config: dict) -> str:
        """The site identity (host) used in ``source``/``subject`` — the URL's
        host, or an explicit ``site`` override in config."""
        return config.get("site") or urlparse(config["url"]).netloc

    async def fetch(
        self, *, org_id: str, config: dict, secret: str | None, since: str | None
    ) -> FetchResult:
        url = config.get("url")
        if not url:
            raise RuntimeError("url source needs a 'url' in its config")
        url = normalize_url(url)
        site = self.site_of({**config, "url": url})
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True, headers={"User-Agent": self.user_agent}
        ) as client:
            try:
                r = await client.get(url)
            except httpx.HTTPError as e:
                raise RuntimeError(f"could not fetch {url}: {e}") from e
        if r.status_code != 200:
            raise RuntimeError(f"fetch failed (HTTP {r.status_code}) for {url}")
        ctype = r.headers.get("content-type", "")
        if ctype and "html" not in ctype and "text" not in ctype:
            raise RuntimeError(f"{url} is {ctype!r}, not a readable HTML/text page")

        body = r.text[: self.max_bytes]
        text = extract_text(body)
        token = _freshness_token(r, text)
        if since is not None and since == token:
            return FetchResult(events=[], cursor=since)  # unchanged since last poll

        event = page_event(
            org_id=org_id,
            site=site,
            url=url,
            title=extract_title(body),
            text=text,
            status=r.status_code,
            token=token,
        )
        return FetchResult(events=[event], cursor=token)
