"""Sitemap connector — crawls the pages listed in a site's ``sitemap.xml``.

The user gives us one sitemap URL; we treat the site as a *polling* source: each
sync re-reads the sitemap, picks the pages that are new or whose ``<lastmod>``
advanced past our cursor, and crawls those pages into ``com.web.page`` events.

Crawling is deliberately *polite* — a slow site must never be hammered:

* only ``max_pages`` are crawled per sync, freshest (``lastmod``) first;
* requests run under a small concurrency cap with a per-request delay;
* ``robots.txt`` is honoured (a disallowed page is skipped, not fetched);
* each response is bounded by a timeout and a byte cap.

The same discovery + per-page crawl helpers back two execution paths: the inline
:meth:`SitemapConnector.fetch` (used by the synchronous sync endpoint and small
sites) and the Celery fan-out in :mod:`meaninggrid_ingest.crawler` (one
rate-limited task per URL, for large sitemaps). Both share this file's logic so
the event shape and politeness rules can't drift apart.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from urllib import robotparser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx
from meaninggrid_shared import CloudEvent, utcnow

from meaninggrid_ingest.connectors.base import FetchResult, PollingConnector

log = logging.getLogger("ingest.sitemap")

# Politeness / safety defaults (overridable per-source via config, or globally
# via IngestSettings → SitemapConnector kwargs).
DEFAULT_MAX_PAGES = 50  # pages crawled per sync
DEFAULT_DELAY = 1.0  # seconds paused before each page request
DEFAULT_CONCURRENCY = 4  # simultaneous in-flight requests
DEFAULT_TIMEOUT = 20.0  # per-request timeout (seconds)
DEFAULT_MAX_BYTES = 2_000_000  # response body read cap (2 MB)
DEFAULT_USER_AGENT = "MeaningGridBot/1.0 (+https://meaninggrid.dev/bot)"

# Discovery bounds — keep a pathological sitemap-index from fanning out forever.
_MAX_CHILD_SITEMAPS = 50  # nested <sitemap> documents fetched per sync
_MAX_ENTRIES = 50_000  # candidate URLs held in memory per sync

_TAG_STRIP = re.compile(r"(?is)<(script|style|template|noscript)\b.*?</\1>")
_TAGS = re.compile(r"(?s)<[^>]+>")
_TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_WS = re.compile(r"\s+")


@dataclass
class SitemapEntry:
    loc: str
    lastmod: str | None  # normalized ISO-8601, or None when the sitemap omits it


class TransientCrawlError(Exception):
    """A page asked us to back off (HTTP 429/503). The inline crawl treats it as
    a skip; the Celery crawl re-queues the URL after ``retry_after`` seconds so a
    struggling origin gets breathing room instead of a retry storm."""

    def __init__(self, url: str, status: int, retry_after: float | None) -> None:
        super().__init__(f"{url} → HTTP {status} (retry after {retry_after}s)")
        self.url = url
        self.status = status
        self.retry_after = retry_after


def _retry_after(r: httpx.Response) -> float | None:
    raw = r.headers.get("Retry-After")
    if raw and raw.isdigit():
        return float(raw)
    return None


# -- sitemap XML parsing ----------------------------------------------------
def _localname(tag: str) -> str:
    """Drop any ``{namespace}`` prefix ElementTree prepends (sitemaps are
    namespaced, but real-world files use inconsistent/again-no namespaces)."""
    return tag.rsplit("}", 1)[-1].lower()


def _normalize_lastmod(raw: str | None) -> str | None:
    """Parse a sitemap ``<lastmod>`` (date or full datetime) to a comparable ISO
    string, or ``None`` if absent/unparseable. Lexicographic compare on the
    result orders correctly because every value is zero-padded ISO-8601."""
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except ValueError:
        # A bare date (YYYY-MM-DD) is already sortable as-is.
        return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None


def _maybe_gunzip(content: bytes, url: str) -> bytes:
    """Transparently decompress a ``.xml.gz`` sitemap (some sites serve them)."""
    if url.lower().endswith(".gz") or content[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(content)
        except (OSError, EOFError):
            return content
    return content


def parse_sitemap(content: bytes, *, url: str) -> tuple[list[SitemapEntry], list[str]]:
    """Parse one sitemap document into ``(page_entries, child_sitemap_urls)``.

    Handles both ``<urlset>`` (pages) and ``<sitemapindex>`` (links to more
    sitemaps); relative ``<loc>`` values are resolved against ``url``. Malformed
    XML yields ``([], [])`` rather than raising — one bad child sitemap shouldn't
    abort the whole crawl.
    """
    raw = _maybe_gunzip(content, url)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        log.warning("sitemap parse failed for %s", url)
        return [], []

    entries: list[SitemapEntry] = []
    children: list[str] = []
    for node in root.iter():
        name = _localname(node.tag)
        if name not in ("url", "sitemap"):
            continue
        loc = lastmod = None
        for child in node:
            cn = _localname(child.tag)
            if cn == "loc" and child.text:
                loc = child.text.strip()
            elif cn == "lastmod":
                lastmod = child.text
        if not loc:
            continue
        absolute = urljoin(url, loc)
        if name == "sitemap":
            children.append(absolute)
        else:
            entries.append(SitemapEntry(loc=absolute, lastmod=_normalize_lastmod(lastmod)))
    return entries, children


def select_entries(
    entries: list[SitemapEntry], *, since: str | None, max_pages: int | None
) -> list[SitemapEntry]:
    """The entries worth crawling this sync: those new since ``since`` (cursor =
    the highest ``lastmod`` fully crawled so far), **oldest first**, optionally
    capped at ``max_pages`` (``None`` = no cap → *every* changed page).

    Oldest-first is what makes full coverage possible: the cursor walks forward
    through the whole set over successive polls, so a capped poll resumes where
    the last one stopped instead of permanently skipping the tail (see
    :func:`_safe_cursor`). An entry with no ``lastmod`` can't be proven unchanged,
    so it's always a candidate (a sitemap that omits ``lastmod`` re-checks those
    pages every poll — still bounded by the per-URL rate limit).
    """
    fresh = [e for e in entries if since is None or e.lastmod is None or e.lastmod > since]
    # Oldest dated first (so the watermark advances forward); undated entries
    # trail in sitemap order (no timestamp to order or skip them by).
    fresh.sort(key=lambda e: (e.lastmod is None, e.lastmod or ""))
    return fresh if max_pages is None else fresh[:max_pages]


def _safe_cursor(
    selected: list[SitemapEntry], dropped_first: SitemapEntry | None, previous: str | None
) -> str | None:
    """Advance the watermark only past pages we *actually crawled* — never to a
    ``lastmod`` whose page set we didn't finish — so a capped poll can't skip the
    pages it deferred.

    ``selected`` is oldest-first; ``dropped_first`` is the first entry the cap
    left behind (``None`` when nothing was dropped). If that deferred page shares
    the newest crawled ``lastmod``, that timestamp's group is split across the cap
    boundary, so we back the cursor off to the last *fully* crawled timestamp.
    Never moves backwards below ``previous``.
    """
    dated = sorted(e.lastmod for e in selected if e.lastmod)
    if not dated:
        return previous
    hi = dated[-1]
    if dropped_first is not None and dropped_first.lastmod == hi:
        lower = [m for m in dated if m < hi]  # the `hi` group is incomplete — back off
        candidate = lower[-1] if lower else None
    else:
        candidate = hi
    return max([c for c in (candidate, previous) if c], default=None)


# -- page text extraction ---------------------------------------------------
def extract_title(body: str) -> str | None:
    m = _TITLE.search(body)
    return _WS.sub(" ", html.unescape(m.group(1))).strip() if m else None


def extract_text(body: str) -> str:
    """A dependency-free "readable text" pass: drop script/style, strip tags,
    unescape entities, collapse whitespace. Good enough to give the context
    pipeline the page's prose without pulling in a full HTML parser."""
    no_blocks = _TAG_STRIP.sub(" ", body)
    text = _TAGS.sub(" ", no_blocks)
    return _WS.sub(" ", html.unescape(text)).strip()


def page_event(
    *,
    org_id: str,
    site: str,
    url: str,
    title: str | None,
    text: str,
    status: int,
    lastmod: str | None,
) -> CloudEvent:
    """One crawled page → one CloudEvent. The id is stable per ``(url, lastmod)``
    so a re-crawl of an *unchanged* page dedupes (same id), while a page whose
    ``lastmod`` advanced produces a fresh id — mirroring the GitHub connector's
    ``updated_at``-in-id scheme."""
    key = hashlib.sha1(url.encode()).hexdigest()[:16]  # noqa: S324 — id, not security
    event_id = f"web-{key}-{lastmod}" if lastmod else f"web-{key}"
    return CloudEvent(
        id=event_id,
        source=f"sitemap:{site}",
        type="com.web.page",
        subject=f"site:{site}",
        time=datetime.fromisoformat(lastmod) if lastmod else utcnow(),
        mgtenant=org_id,
        data={
            "url": url,
            "site": site,
            "title": title,
            "text": PollingConnector.clip(text),
            "status": status,
            "lastmod": lastmod,
        },
    )


class SitemapConnector(PollingConnector):
    kind = "sitemap"

    def __init__(
        self,
        *,
        max_pages: int = DEFAULT_MAX_PAGES,
        delay: float = DEFAULT_DELAY,
        concurrency: int = DEFAULT_CONCURRENCY,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        respect_robots: bool = True,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.max_pages = max_pages
        self.delay = delay
        self.concurrency = max(1, concurrency)
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        self.user_agent = user_agent

    @classmethod
    def from_settings(cls, s) -> SitemapConnector:  # noqa: ANN001 — duck-typed IngestSettings
        """Build a connector from the deployment's crawl budget so the inline and
        Celery paths share one source of politeness configuration."""
        return cls(
            max_pages=s.crawl_max_pages,
            delay=s.crawl_delay_seconds,
            concurrency=s.crawl_concurrency,
            timeout=s.crawl_timeout_seconds,
            max_bytes=s.crawl_max_bytes,
            respect_robots=s.crawl_respect_robots,
            user_agent=s.crawl_user_agent,
        )

    @staticmethod
    def site_of(config: dict) -> str:
        """The site identity (host) used in ``source``/``subject`` — derived from
        the sitemap URL, or an explicit ``site`` override in config."""
        return config.get("site") or urlparse(config["sitemap_url"]).netloc

    # -- discovery ----------------------------------------------------------
    async def discover(
        self,
        *,
        config: dict,
        since: str | None,
        client: httpx.AsyncClient | None = None,
        max_pages: int | None = None,
    ) -> tuple[list[SitemapEntry], str | None]:
        """Read the sitemap (recursing into a sitemap index), apply robots.txt,
        and return ``(entries_to_crawl, next_cursor)``.

        ``max_pages`` caps this poll (``None`` = no cap → every changed page; used
        by the Celery crawler so it checks *all* pages, with the per-URL rate limit
        keeping it polite). The cursor only advances past pages this poll fully
        covered, so a capped poll resumes the rest next time instead of skipping
        them. Shared by the inline ``fetch`` and the Celery path.
        """
        sitemap_url = config["sitemap_url"]
        own_client = client is None
        client = client or httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True, headers={"User-Agent": self.user_agent}
        )
        try:
            all_entries = await self._collect_entries(client, sitemap_url)
            if self.respect_robots:
                rp = await self._load_robots(client, sitemap_url)
                if rp is not None:
                    all_entries = [e for e in all_entries if rp.can_fetch(self.user_agent, e.loc)]
            ordered = select_entries(all_entries, since=since, max_pages=None)  # oldest-first
            if max_pages is None or len(ordered) <= max_pages:
                return ordered, _safe_cursor(ordered, None, since)
            selected = ordered[:max_pages]
            return selected, _safe_cursor(selected, ordered[max_pages], since)
        finally:
            if own_client:
                await client.aclose()

    async def _collect_entries(
        self, client: httpx.AsyncClient, sitemap_url: str
    ) -> list[SitemapEntry]:
        """BFS over a sitemap (index → child sitemaps → pages), bounded by
        ``_MAX_CHILD_SITEMAPS`` / ``_MAX_ENTRIES`` and throttled by ``delay``."""
        entries: list[SitemapEntry] = []
        queue = [sitemap_url]
        seen: set[str] = set()
        fetched = 0
        while queue and len(entries) < _MAX_ENTRIES:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            if self.delay:
                await asyncio.sleep(self.delay)
            content = await self._get_sitemap(client, current)
            if content is None:
                continue
            page_entries, children = parse_sitemap(content, url=current)
            entries.extend(page_entries)
            for child in children:
                if fetched < _MAX_CHILD_SITEMAPS and child not in seen:
                    queue.append(child)
                    fetched += 1
        if len(entries) > _MAX_ENTRIES:
            log.warning("sitemap %s exceeded %d entries; truncating", sitemap_url, _MAX_ENTRIES)
        return entries[:_MAX_ENTRIES]

    async def _get_sitemap(self, client: httpx.AsyncClient, url: str) -> bytes | None:
        """Fetch one sitemap document. The *top-level* sitemap failing is fatal
        (the source is misconfigured — surfaced to the user as a sync error); a
        failing nested child is logged and skipped."""
        try:
            r = await client.get(url)
        except httpx.HTTPError as e:
            raise RuntimeError(f"could not fetch sitemap {url}: {e}") from e
        if r.status_code == 404:
            raise RuntimeError(f"sitemap not found (404) at {url} — check the URL")
        if r.status_code >= 400:
            raise RuntimeError(f"sitemap fetch failed ({r.status_code}) at {url}")
        return r.content

    async def _load_robots(
        self, client: httpx.AsyncClient, sitemap_url: str
    ) -> robotparser.RobotFileParser | None:
        """Fetch + parse ``/robots.txt`` for the site. A missing or unreachable
        robots file means "no restrictions" (the standard interpretation)."""
        p = urlparse(sitemap_url)
        robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
        try:
            r = await client.get(robots_url)
        except httpx.HTTPError:
            return None
        if r.status_code >= 400:
            return None
        rp = robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp

    # -- per-page crawl -----------------------------------------------------
    async def crawl_page(
        self,
        client: httpx.AsyncClient,
        entry: SitemapEntry,
        *,
        org_id: str,
        site: str,
    ) -> CloudEvent | None:
        """Fetch a single page and build its event, or ``None`` to skip it (non-OK
        status, non-HTML body, or a transport error). Skipping a page never fails
        the sync — one dead link shouldn't sink the rest."""
        try:
            r = await client.get(entry.loc)
        except httpx.HTTPError as e:
            log.info("skip %s: %s", entry.loc, e)
            return None
        if r.status_code in (429, 503):  # the site is asking us to slow down
            raise TransientCrawlError(entry.loc, r.status_code, _retry_after(r))
        if r.status_code != 200:
            log.info("skip %s: HTTP %s", entry.loc, r.status_code)
            return None
        ctype = r.headers.get("content-type", "")
        if ctype and "html" not in ctype and "text" not in ctype:
            return None  # binary/asset — nothing to read
        body = r.text[: self.max_bytes]
        return page_event(
            org_id=org_id,
            site=site,
            url=entry.loc,
            title=extract_title(body),
            text=extract_text(body),
            status=r.status_code,
            lastmod=entry.lastmod,
        )

    # -- PollingConnector contract (inline, polite crawl) -------------------
    async def fetch(
        self, *, org_id: str, config: dict, secret: str | None, since: str | None
    ) -> FetchResult:
        """Discover + crawl inline, throttled to ``concurrency`` in-flight
        requests each preceded by ``delay``, and **bounded to ``max_pages``** —
        this is one blocking call (the synchronous sync endpoint + add-source
        connection test), so it samples a bounded batch rather than a whole large
        site. Full coverage is the Celery fan-out's job (``discover`` with no cap,
        one rate-limited task per URL); the safe cursor means this bounded sync
        won't make that fan-out skip the pages it deferred.
        """
        site = self.site_of(config)
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True, headers={"User-Agent": self.user_agent}
        ) as client:
            entries, cursor = await self.discover(
                config=config, since=since, client=client, max_pages=self.max_pages
            )
            sem = asyncio.Semaphore(self.concurrency)

            async def crawl(entry: SitemapEntry) -> CloudEvent | None:
                async with sem:
                    if self.delay:
                        await asyncio.sleep(self.delay)
                    try:
                        return await self.crawl_page(client, entry, org_id=org_id, site=site)
                    except TransientCrawlError as e:
                        log.info("skip (backoff) %s", e)  # no scheduler inline — skip
                        return None

            results = await asyncio.gather(*(crawl(e) for e in entries))

        events = [e for e in results if e is not None]
        events.sort(key=lambda e: e.time)
        return FetchResult(events=events, cursor=cursor)
