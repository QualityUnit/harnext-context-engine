"""LiveAgent connector — polls a department's tickets as CloudEvents.

LiveAgent is self-hosted/SaaS helpdesk software: each install lives at its own
base URL and issues a *v3 API key* (sent as the ``apikey`` header). There's no
OAuth — the user pastes their base URL + key once as a project integration, then
connects a *source* by choosing a department (and optionally a tag) whose tickets
should be indexed.

This is a *polling* connector that **walks** a department's tickets in date order
rather than pulling a fixed window: ``GET /api/v3/tickets`` sorted by
``date_changed`` ascending, filtered to the department (+ tag). The cursor is
``"<date_changed>|<ticket_id>"`` — the last ticket processed — fed back as a
``date_changed >=`` filter so each poll resumes exactly where the last left off
and steps forward one page at a time. For each ticket we also pull its messages
(``GET /api/v3/tickets/{id}/messages``) and fold their text into the event body,
so the indexed context is the actual conversation, not just the subject line.

Dates are requested in UTC (``Timezone-Offset: 0``) so the stored cursor and the
filter value we send back speak the same clock.
"""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from meaninggrid_shared import CloudEvent

from meaninggrid_ingest.connectors.base import (
    FetchResult,
    PollingConnector,
    RateLimitedError,
    parse_retry_after,
)

_API_PATH = "/api/v3"
_BODY_CLIP = 1200
# Per-poll ceiling. A department's full history is walked across many polls (the
# cursor advances each time), so one sync stays bounded and the scheduler does
# the rest. Also the page size we ask LiveAgent for.
_PER_POLL = 50
# How many messages of a ticket to fold into the body (oldest first).
_MAX_MESSAGES = 20
_TAG = re.compile(r"<[^>]+>")


def normalize_base_url(raw: str) -> str:
    """Coerce a pasted LiveAgent URL to a bare ``scheme://host`` origin.

    Accepts ``https://x.ladesk.com``, a trailing slash, an accidental
    ``/api/v3`` suffix, or a missing scheme (assumed https)."""
    s = raw.strip()
    if not re.match(r"^https?://", s, flags=re.I):
        s = "https://" + s
    s = re.sub(r"/+$", "", s)
    s = re.sub(r"/api/v3/?$", "", s, flags=re.I)
    return s.rstrip("/")


def _strip_html(s: str | None) -> str:
    """Flatten a LiveAgent message body (often HTML) to plain text, collapsing
    runs of whitespace (incl. the ``&nbsp;`` → NBSP that entity-unescaping yields)."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", s))).strip()


def _clip(s: str) -> str:
    return s if len(s) <= _BODY_CLIP else s[:_BODY_CLIP] + "…"


def _parse_dt(s: str | None) -> datetime:
    """Parse a LiveAgent ``YYYY-MM-DD HH:MM:SS`` (UTC) timestamp; ISO as a
    fallback; ``now`` if absent/unparseable."""
    if s:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                pass
    return datetime.now(UTC)


def _as_list(payload: Any) -> list[dict[str, Any]]:
    """LiveAgent list endpoints return a bare JSON array; tolerate a wrapped
    ``{"data"|"items"|...: [...]}`` shape too."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in ("data", "items", "results", "tickets"):
            v = payload.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _message_texts(payload: Any) -> list[str]:
    """Pull every message body out of a ``/tickets/{id}/messages`` response,
    whatever the nesting (groups → messages, or a flat list). Tolerant by design
    so it survives shape differences across LiveAgent versions."""
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            msg = node.get("message")
            if isinstance(msg, str) and msg.strip():
                out.append(msg)
            for v in node.values():
                if isinstance(v, list | dict):
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return out


def _ticket_id(t: dict[str, Any]) -> str:
    return str(t.get("id") or t.get("ticketid") or t.get("conversationid") or "")


def _changed(t: dict[str, Any]) -> str:
    return str(t.get("date_changed") or t.get("datechanged") or "")


def _split_cursor(since: str | None) -> tuple[str | None, str | None]:
    """``"<date_changed>|<ticket_id>"`` → ``(date, id)``."""
    if not since:
        return None, None
    date, _, tid = since.partition("|")
    return (date or None), (tid or None)


class LiveAgentConnector(PollingConnector):
    kind = "liveagent"

    def __init__(self, per_poll: int = _PER_POLL, fetch_messages: bool = True) -> None:
        self.per_poll = per_poll
        self.fetch_messages = fetch_messages

    async def fetch(
        self, *, org_id: str, config: dict[str, Any], secret: str | None, since: str | None
    ) -> FetchResult:
        if not secret:
            raise RuntimeError("LiveAgent source requires an API key")
        base = config.get("base_url")
        department_id = config.get("department_id")
        if not base or not department_id:
            raise RuntimeError("LiveAgent source needs a base URL and a department")
        department_name = config.get("department_name") or department_id
        tag_id = config.get("tag_id")
        subject = f"department:{department_name}"

        since_date, since_id = _split_cursor(since)
        filters: list[list[str]] = [["departmentid", "E", str(department_id)]]
        if tag_id:
            filters.append(["tags", "CY", str(tag_id)])  # CY = contains any of
        if since_date:
            filters.append(["date_changed", "D>=", since_date])  # inclusive; boundary skipped below

        params = {
            "_page": 1,
            "_perPage": self.per_poll,
            "_sortField": "date_changed",
            "_sortDir": "ASC",
            "_filters": json.dumps(filters, separators=(",", ":")),
        }

        async with httpx.AsyncClient(
            base_url=base + _API_PATH,
            timeout=30,
            headers={"apikey": secret, "Accept": "application/json", "Timezone-Offset": "0"},
        ) as client:
            r = await client.get("/tickets", params=params)
            self._raise_for_liveagent(r)
            tickets = _as_list(r.json())

            events: list[CloudEvent] = []
            cursor = since
            for t in tickets:
                tid = _ticket_id(t)
                changed = _changed(t)
                if not tid:
                    continue
                # Skip the exact boundary ticket re-returned by the inclusive
                # date filter; anything past it is new.
                if since_date and changed == since_date and tid == since_id:
                    continue
                body = ""
                if self.fetch_messages:
                    body = await self._ticket_body(client, tid)
                events.append(self._ticket_event(org_id, subject, department_id, t, body))
                cursor = f"{changed}|{tid}"

        events.sort(key=lambda e: e.time)
        return FetchResult(events=events, cursor=cursor)

    async def _ticket_body(self, client: httpx.AsyncClient, ticket_id: str) -> str:
        """Best-effort: fold a ticket's messages into one clipped text block.
        A messages fetch failing must not sink the whole sync — we still index
        the ticket's metadata."""
        try:
            r = await client.get(f"/tickets/{ticket_id}/messages")
            if r.status_code != 200:
                return ""
            texts = [_strip_html(m) for m in _message_texts(r.json())]
            texts = [t for t in texts if t][:_MAX_MESSAGES]
            return _clip("\n\n".join(texts))
        except httpx.HTTPError:
            return ""

    def _ticket_event(
        self,
        org_id: str,
        subject: str,
        department_id: str,
        t: dict[str, Any],
        body: str,
    ) -> CloudEvent:
        tid = _ticket_id(t)
        changed = _changed(t)
        # date_changed in the id so an updated ticket re-indexes on a later poll
        # (a fresh event id), while a single sync still emits each ticket once.
        stamp = re.sub(r"\D", "", changed) or "0"
        return CloudEvent(
            id=f"liveagent-{tid}-{stamp}",
            source=f"liveagent:{department_id}",
            type="com.liveagent.ticket",
            subject=subject,
            time=_parse_dt(changed or str(t.get("date_created") or t.get("datecreated"))),
            mgtenant=org_id,
            data={
                "ticket_id": tid,
                "code": t.get("code"),
                "title": t.get("subject"),
                "status": t.get("status"),
                "department_id": department_id,
                "owner_name": t.get("owner_name") or t.get("ownername"),
                "owner_email": t.get("owner_email") or t.get("owneremail"),
                "tags": t.get("tags"),
                "channel_type": t.get("channel_type"),
                "date_created": t.get("date_created") or t.get("datecreated"),
                "date_changed": changed,
                "body": body,
            },
        )

    @staticmethod
    def _raise_for_liveagent(r: httpx.Response) -> None:
        if r.status_code == 401:
            raise RuntimeError("LiveAgent rejected the API key — it's invalid")
        if r.status_code == 403:
            raise RuntimeError("LiveAgent denied access (403) — the key lacks permission")
        if r.status_code == 404:
            raise RuntimeError(
                "LiveAgent endpoint not found (404) — check the base URL (it must be the "
                "install's root, e.g. https://yourco.ladesk.com)"
            )
        if r.status_code == 429:
            raise RateLimitedError("LiveAgent", parse_retry_after(r.headers))
        r.raise_for_status()


# -- control-plane helpers (used by the API to validate creds + populate the
#    source-picker dropdowns; the data-plane fetch above stays self-contained) --


async def _list(base_url: str, api_key: str, path: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        base_url=normalize_base_url(base_url) + _API_PATH,
        timeout=20,
        headers={"apikey": api_key, "Accept": "application/json"},
    ) as client:
        r = await client.get(path, params={"_perPage": 200})
        LiveAgentConnector._raise_for_liveagent(r)
        return _as_list(r.json())


async def list_departments(base_url: str, api_key: str) -> list[dict[str, str]]:
    # LiveAgent's Department object keys the id as ``department_id`` (only Tag uses
    # ``id``). Reading ``id`` here matched nothing, so the picker came up empty even
    # though departments exist. Prefer ``department_id``, tolerate ``id`` as a fallback.
    rows = await _list(base_url, api_key, "/departments")
    out: list[dict[str, str]] = []
    for d in rows:
        did = d.get("department_id") or d.get("id")
        if did is None:
            continue
        out.append({"id": str(did), "name": d.get("name") or str(did)})
    return out


async def list_tags(base_url: str, api_key: str) -> list[dict[str, str]]:
    rows = await _list(base_url, api_key, "/tags")
    return [
        {"id": str(d.get("id")), "name": d.get("name") or str(d.get("id"))}
        for d in rows
        if d.get("id") is not None
    ]


async def verify_credentials(base_url: str, api_key: str) -> None:
    """Raise with a friendly message if the base URL + key can't list
    departments — the cheapest authenticated call there is."""
    await list_departments(base_url, api_key)
