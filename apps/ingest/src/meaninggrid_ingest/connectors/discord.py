"""Discord connector — polls a channel's recent messages as CloudEvents.

Discord has no Slack-style "POST every message to a URL" webhook (real-time
messages only come over the Gateway WebSocket), so this is a *polling* connector:
``fetch`` pulls ``GET /channels/{id}/messages`` with a bot token. The cursor is a
message snowflake fed back as ``?after=`` — Discord returns newest-first, so we
reverse to chronological. Each message → one event with ``subject = channel:<name>``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from meaninggrid_shared import CloudEvent

from meaninggrid_ingest.connectors.base import (
    FetchResult,
    PollingConnector,
    RateLimitedError,
    parse_retry_after,
)

_API = "https://discord.com/api/v10"


def _parse_ts(s: str | None) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else datetime.now().astimezone()


class DiscordConnector(PollingConnector):
    kind = "discord"

    def __init__(self, limit: int = 100) -> None:
        self.limit = limit

    async def fetch(
        self, *, org_id: str, config: dict[str, Any], secret: str | None, since: str | None
    ) -> FetchResult:
        if not secret:
            raise RuntimeError("Discord source requires a bot token")
        channel_id = config["channel_id"]
        channel_name = config.get("channel_name", channel_id)
        guild_id = config.get("guild_id", "")
        params: dict[str, Any] = {"limit": self.limit}
        if since:
            params["after"] = since  # snowflake watermark (exclusive)

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{_API}/channels/{channel_id}/messages",
                params=params,
                headers={"Authorization": f"Bot {secret}"},
            )
            self._raise_for_discord(r)
            messages = r.json()  # newest-first

        events: list[CloudEvent] = []
        max_id = since
        for m in reversed(messages):  # -> chronological (oldest first)
            mid = m["id"]
            content = m.get("content")
            events.append(
                self.chat_message_event(
                    provider="discord",
                    org_id=org_id,
                    source_id=f"{guild_id}:{channel_id}",
                    channel_id=channel_id,
                    channel_name=channel_name,
                    message_id=mid,
                    time=_parse_ts(m.get("timestamp")),
                    text=content,
                    extra={
                        "guild_id": guild_id,
                        "author": (m.get("author") or {}).get("username"),
                        "content": self.clip(content),
                        "message_id": mid,
                    },
                )
            )
            if max_id is None or int(mid) > int(max_id):  # snowflakes compare as ints
                max_id = mid

        events.sort(key=lambda e: e.time)
        return FetchResult(events=events, cursor=max_id)

    @staticmethod
    def _raise_for_discord(r: httpx.Response) -> None:
        if r.status_code == 401:
            raise RuntimeError("Discord rejected the bot token — it's invalid")
        if r.status_code == 403:
            raise RuntimeError(
                "Discord denied access (403) — the bot lacks permission or isn't in this channel"
            )
        if r.status_code == 404:
            raise RuntimeError(
                "Discord channel not found — check the channel id and that the bot is invited"
            )
        if r.status_code == 429:
            raise RateLimitedError("Discord", parse_retry_after(r.headers))
        r.raise_for_status()
