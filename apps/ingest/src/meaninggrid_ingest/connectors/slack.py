"""Slack connector — pulls a channel's recent messages as CloudEvents.

Uses the Slack Web API ``conversations.history`` with a bot/user token. Each
message becomes one event with ``subject = channel:<id>``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from meaninggrid_shared import CloudEvent

from meaninggrid_ingest.connectors.base import FetchResult

_API = "https://slack.com/api"
_BODY_CLIP = 1200


def _clip(s: str | None) -> str:
    s = s or ""
    return s if len(s) <= _BODY_CLIP else s[:_BODY_CLIP] + "…"


class SlackConnector:
    kind = "slack"

    def __init__(self, limit: int = 50) -> None:
        self.limit = limit

    async def fetch(
        self, *, org_id: str, config: dict[str, Any], secret: str | None, since: str | None
    ) -> FetchResult:
        if not secret:
            raise RuntimeError("Slack source requires a bot/user token")
        channel = config["channel_id"]
        channel_name = config.get("channel_name", channel)
        subject = f"channel:{channel_name}"
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
            ts = m["ts"]  # "1700000000.000100"
            events.append(
                CloudEvent(
                    id=f"slack-{channel}-{ts}",
                    source=f"slack:{channel}",
                    type="com.slack.message",
                    subject=subject,
                    time=datetime.fromtimestamp(float(ts), tz=UTC),
                    mgtenant=org_id,
                    data={
                        "channel": channel,
                        "channel_name": channel_name,
                        "user": m.get("user"),
                        "text": _clip(m.get("text")),
                        "ts": ts,
                        "reply_count": m.get("reply_count", 0),
                    },
                )
            )
            if max_ts is None or float(ts) > float(max_ts):
                max_ts = ts

        events.sort(key=lambda e: e.time)
        return FetchResult(events=events, cursor=max_ts)
