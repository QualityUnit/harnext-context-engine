"""Slack connector — both a poller and an Events-API webhook receiver.

``fetch`` pulls a channel's recent messages via ``conversations.history``;
``verify``/``parse`` authenticate and decode the inbound Events API webhook. Both
paths emit the same ``CloudEvent`` (via ``slack_message_event``) so a message
seen by both dedupes on ``id``. Each message → one event with
``subject = channel:<name>``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
from meaninggrid_shared import CloudEvent

from meaninggrid_ingest.connectors.base import (
    Connector,
    EventConnector,
    FetchResult,
    PollingConnector,
)
from meaninggrid_ingest.security import verify_slack_signature

_API = "https://slack.com/api"


def slack_message_event(org_id: str, channel: str, channel_name: str, m: dict) -> CloudEvent:
    """Map one Slack message dict (from the poller or the Events API) to a
    CloudEvent. Shared by the poll and webhook paths so their output can't drift."""
    ts = m["ts"]  # "1700000000.000100"
    return Connector.chat_message_event(
        provider="slack",
        org_id=org_id,
        source_id=channel,
        channel_id=channel,
        channel_name=channel_name,
        message_id=ts,
        time=datetime.fromtimestamp(float(ts), tz=UTC),
        text=m.get("text"),
        extra={"user": m.get("user"), "ts": ts, "reply_count": m.get("reply_count", 0)},
    )


class SlackConnector(EventConnector, PollingConnector):
    kind = "slack"

    def __init__(self, limit: int = 50) -> None:
        self.limit = limit

    # -- polling (pull) ----------------------------------------------------
    async def fetch(
        self, *, org_id: str, config: dict[str, Any], secret: str | None, since: str | None
    ) -> FetchResult:
        if not secret:
            raise RuntimeError("Slack source requires a bot/user token")
        channel = config["channel_id"]
        channel_name = config.get("channel_name", channel)
        params: dict[str, Any] = {"channel": channel, "limit": self.limit}
        if since:
            params["oldest"] = since  # slack ts cursor

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{_API}/conversations.history",
                params=params,
                headers={"Authorization": f"Bearer {secret}"},
            )
            r.raise_for_status()
            body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Slack API error: {body.get('error')}")

        events: list[CloudEvent] = []
        max_ts = since
        for m in body.get("messages", []):
            ts = m["ts"]
            events.append(slack_message_event(org_id, channel, channel_name, m))
            if max_ts is None or float(ts) > float(max_ts):
                max_ts = ts

        events.sort(key=lambda e: e.time)
        return FetchResult(events=events, cursor=max_ts)

    # -- event (push) ------------------------------------------------------
    def verify(self, *, secret: str, headers: Mapping[str, str], body: bytes) -> bool:
        return verify_slack_signature(
            secret,
            headers.get("X-Slack-Request-Timestamp", ""),
            headers.get("X-Slack-Signature", ""),
            body.decode("utf-8", "replace"),
        )

    def parse(
        self, *, headers: Mapping[str, str], body: bytes
    ) -> tuple[dict | None, list[tuple]]:
        payload = json.loads(body)
        if payload.get("type") == "url_verification":  # one-time endpoint handshake
            return {"challenge": payload.get("challenge")}, []
        if payload.get("type") == "event_callback":
            ev = payload.get("event") or {}
            # only real, top-level user messages — skip edits/deletes/joins and bots
            if ev.get("type") == "message" and not ev.get("subtype") and not ev.get("bot_id"):
                return None, [(payload.get("team_id"), ev)]
        return None, []
