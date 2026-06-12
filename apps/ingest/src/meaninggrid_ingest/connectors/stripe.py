"""Stripe connector — polls an account's events as CloudEvents.

Stripe is connected with a **read-only Restricted API key** (no OAuth): the user
creates a key scoped to *Events · read* in their Stripe dashboard and pastes it
once as a project integration, then connects a single *source* that indexes every
event the account emits.

This is a *polling* connector that **walks** ``GET /v1/events`` forward in time.
Stripe returns events newest-first; the cursor is the id of the newest event seen
so far, fed back as ``ending_before`` so each poll fetches only events newer than
the cursor (one page at a time — the scheduler walks the rest). The first sync
(no cursor) takes the most recent page, then advances forward on every poll, the
same bounded-first-sync behaviour as the GitHub/LiveAgent connectors.

Event ids (``evt_…``) are unique and immutable, so ``stripe-{id}`` is the natural
``IngestedEvent`` dedup key.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
from meaninggrid_shared import CloudEvent

from meaninggrid_ingest.connectors.base import (
    Connector,
    FetchResult,
    PollingConnector,
    RateLimitedError,
    parse_retry_after,
)

_API_BASE = "https://api.stripe.com"
# Stripe's max page size. A busy account's backlog is walked across many polls
# (the cursor advances each time), so one sync stays bounded.
_PER_POLL = 100
# Underlying-object fields worth surfacing flat (most events carry a subset).
_SUMMARY_FIELDS = (
    "amount",
    "amount_due",
    "amount_paid",
    "currency",
    "status",
    "description",
    "customer",
    "email",
    "name",
    "number",
)


def _ts(created: Any) -> datetime:
    """Stripe timestamps are unix seconds (UTC); fall back to now if absent."""
    if isinstance(created, int):
        return datetime.fromtimestamp(created, tz=UTC)
    return datetime.now(UTC)


def _data_list(payload: Any) -> list[dict[str, Any]]:
    """Stripe list responses are ``{"object": "list", "data": [...]}`` (newest-first)."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    return []


def _summarize(obj: Any) -> dict[str, Any]:
    """A small, bounded view of an event's underlying object: its kind + id, a few
    common human-relevant fields, and a clipped JSON dump (keeps events small)."""
    if not isinstance(obj, dict):
        return {"object": None}
    out: dict[str, Any] = {"object": obj.get("object"), "object_id": obj.get("id")}
    for f in _SUMMARY_FIELDS:
        if obj.get(f) is not None:
            out[f] = obj[f]
    out["summary"] = Connector.clip(json.dumps(obj, separators=(",", ":"), default=str))
    return out


def _account_name(acct: dict[str, Any]) -> str:
    settings = acct.get("settings") or {}
    dashboard = settings.get("dashboard") or {}
    profile = acct.get("business_profile") or {}
    return (
        dashboard.get("display_name")
        or profile.get("name")
        or acct.get("email")
        or acct.get("id")
        or ""
    )


class StripeConnector(PollingConnector):
    kind = "stripe"

    def __init__(self, per_poll: int = _PER_POLL) -> None:
        self.per_poll = per_poll

    async def fetch(
        self, *, org_id: str, config: dict[str, Any], secret: str | None, since: str | None
    ) -> FetchResult:
        if not secret:
            raise RuntimeError("Stripe source requires a Restricted API key")
        account_name = config.get("account_name") or "account"

        params: dict[str, Any] = {"limit": self.per_poll}
        if since:
            # Fetch only events newer than the cursor (Stripe paginates newest-first;
            # ending_before walks toward the head of the list).
            params["ending_before"] = since

        async with httpx.AsyncClient(
            base_url=_API_BASE,
            timeout=30,
            headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
        ) as client:
            r = await client.get("/v1/events", params=params)
            self._raise_for_stripe(r)
            data = _data_list(r.json())

        events = [self._event(org_id, account_name, e) for e in data if e.get("id")]
        events.sort(key=lambda e: e.time)
        # data is newest-first, so data[0] is the new high-watermark.
        cursor = data[0].get("id") if data else since
        return FetchResult(events=events, cursor=cursor)

    def _event(self, org_id: str, account_name: str, evt: dict[str, Any]) -> CloudEvent:
        evt_id = str(evt.get("id") or "")
        evt_type = str(evt.get("type") or "unknown")
        # Group by the top-level resource (charge, customer, invoice, …) so the
        # classifier keeps a meaningful per-resource baseline instead of one stream.
        resource = evt_type.split(".")[0] or "event"
        obj = (evt.get("data") or {}).get("object") if isinstance(evt.get("data"), dict) else None
        return CloudEvent(
            id=f"stripe-{evt_id}",
            source=f"stripe:{account_name}",
            type="com.stripe.event",
            subject=f"stripe:{resource}",
            time=_ts(evt.get("created")),
            mgtenant=org_id,
            data={
                "event_id": evt_id,
                "event_type": evt_type,
                "livemode": evt.get("livemode"),
                "api_version": evt.get("api_version"),
                "created": evt.get("created"),
                **_summarize(obj),
            },
        )

    @staticmethod
    def _raise_for_stripe(r: httpx.Response) -> None:
        if r.status_code == 401:
            raise RuntimeError("Stripe rejected the API key — it's invalid or revoked")
        if r.status_code == 403:
            raise RuntimeError(
                "Stripe denied access (403) — the restricted key lacks the 'Events' read permission"
            )
        if r.status_code == 429:
            raise RateLimitedError("Stripe", parse_retry_after(r.headers))
        r.raise_for_status()


# -- control-plane helper (used by the API to validate the key + resolve a display
#    name; the data-plane fetch above stays self-contained) --------------------


async def verify_credentials(api_key: str) -> dict[str, str]:
    """Validate a Restricted key by reading the events list (the one permission a
    source needs), then best-effort resolve a display name from the account.
    Raises a friendly ``RuntimeError`` if the key can't read events. Returns
    ``{"name": <display>}``."""
    async with httpx.AsyncClient(
        base_url=_API_BASE,
        timeout=20,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    ) as client:
        r = await client.get("/v1/events", params={"limit": 1})
        StripeConnector._raise_for_stripe(r)
        name = "Stripe account"
        try:  # /v1/account is optional — the key may not grant it; that's fine.
            a = await client.get("/v1/account")
            if a.status_code == 200:
                name = _account_name(a.json()) or name
        except httpx.HTTPError:
            pass
    return {"name": name}
