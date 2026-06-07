"""Crawl https://www.liveagent.com/features/ + its feature subpages, extract the
text, and emit one CloudEvent per page into MeaningGrid's raw topic.

The classifier routes them and the builder incorporates them into the target
project's AgentFS — query the result over MCP.

    # create a project in the dashboard first, then:
    uv run --package meaninggrid-ingest python scripts/scrape_liveagent.py <PROJECT_ID> --limit 30
    uv run --package meaninggrid-ingest python scripts/scrape_liveagent.py <PROJECT_ID> --dry-run

All pages share one entity (subject=product:liveagent) so they aggregate into a
few batch windows rather than one build per page.
"""

from __future__ import annotations

import argparse
import asyncio
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from aiokafka import AIOKafkaProducer
from meaninggrid_shared import RAW_EVENTS_TOPIC, CloudEvent

BASE = "https://www.liveagent.com"
INDEX = f"{BASE}/features/"
SUBJECT = "product:liveagent"


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.add(v)


class _TextParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "header", "footer", "nav"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self.description = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = dict(attrs)
            if a.get("name") == "description" and a.get("content"):
                self.description = a["content"] or ""

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._skip == 0:
            t = data.strip()
            if t:
                self.parts.append(t)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def feature_links(html: str) -> list[str]:
    p = _LinkParser()
    p.feed(html)
    out: set[str] = set()
    for href in p.links:
        u = urljoin(BASE, href)
        parsed = urlparse(u)
        if not parsed.netloc.endswith("liveagent.com"):
            continue
        if not parsed.path.startswith("/features/"):
            continue
        slug = parsed.path.rstrip("/").split("/features/", 1)[-1]
        if slug and "/" not in slug:  # a direct feature subpage, not the index
            out.add(f"{BASE}/features/{slug}/")
    return sorted(out)


async def fetch(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url)
    r.raise_for_status()
    return r.text


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id", help="target project id (the mgtenant)")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--max-chars", type=int, default=4000)
    ap.add_argument("--bootstrap", default="localhost:9092")
    ap.add_argument("--dry-run", action="store_true", help="extract + print, do not send")
    args = ap.parse_args()

    headers = {"User-Agent": "meaninggrid-scraper/0.1 (+https://meaninggrid.local)"}
    async with httpx.AsyncClient(
        timeout=30, headers=headers, follow_redirects=True
    ) as client:
        all_links = feature_links(await fetch(client, INDEX))
        links = all_links[: args.limit]
        print(f"discovered {len(all_links)} feature page(s); processing {len(links)} (limit {args.limit})\n")

        producer: AIOKafkaProducer | None = None
        if not args.dry_run:
            producer = AIOKafkaProducer(bootstrap_servers=args.bootstrap)
            await producer.start()

        sent = 0
        try:
            for url in links:
                try:
                    page = await fetch(client, url)
                except Exception as e:  # noqa: BLE001
                    print(f"  skip {url}: {e}")
                    continue
                tp = _TextParser()
                tp.feed(page)
                slug = url.rstrip("/").split("/features/", 1)[-1]
                event = CloudEvent(
                    id=f"web-liveagent-{slug}",
                    source="web:liveagent.com",
                    type="com.web.page",
                    subject=SUBJECT,
                    time=datetime.now(UTC),
                    mgtenant=args.project_id,
                    data={
                        "url": url,
                        "title": tp.title.strip(),
                        "description": tp.description.strip(),
                        "text": tp.text()[: args.max_chars],
                    },
                )
                if producer is not None:
                    await producer.send_and_wait(
                        RAW_EVENTS_TOPIC,
                        value=event.model_dump_json().encode(),
                        key=event.partition_key(),
                    )
                sent += 1
                print(f"  [{slug}] {tp.title.strip()[:60]} ({len(tp.text())} chars)")
                await asyncio.sleep(0.3)  # be polite
        finally:
            if producer is not None:
                await producer.stop()

        verb = "would send" if args.dry_run else "sent"
        print(f"\n{verb} {sent} page event(s) → {RAW_EVENTS_TOPIC} (project {args.project_id})")


if __name__ == "__main__":
    asyncio.run(main())
