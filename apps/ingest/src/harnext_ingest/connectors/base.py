"""Connector taxonomy: two ingestion paradigms over a shared base.

Every source is served by one of two kinds of connector — and a provider may be
both:

* ``PollingConnector`` (*pull*) — ``fetch()`` pulls a source's recent activity on
  a sync (GitHub, Slack, Discord, …).
* ``EventConnector`` (*push*) — a signed webhook delivers events as they happen;
  ``verify()`` authenticates the request and ``parse()`` turns the raw body into
  a handshake reply and/or work for the service to fan out (Slack, GitHub).

Common parts — text clipping and the chat-message → CloudEvent mapping — live on
the shared ``Connector`` base so the poll and webhook paths can't drift apart.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from harnext_shared import CloudEvent

_BODY_CLIP = 1200


@dataclass
class FetchResult:
    events: list[CloudEvent]  # chronological (oldest first)
    cursor: str | None  # new incremental-sync watermark


class Connector(ABC):
    """Base for every connector. Subclasses set ``kind`` and implement one or
    both of the ``PollingConnector`` / ``EventConnector`` contracts."""

    kind: str

    @staticmethod
    def clip(s: str | None, limit: int = _BODY_CLIP) -> str:
        """Clip a body to ``limit`` chars with an ellipsis (keeps events small)."""
        s = s or ""
        return s if len(s) <= limit else s[:limit] + "…"

    @classmethod
    def chat_message_event(
        cls,
        *,
        provider: str,
        org_id: str,
        source_id: str,
        channel_id: str,
        channel_name: str,
        message_id: str,
        time: datetime,
        text: str | None,
        extra: dict[str, Any] | None = None,
    ) -> CloudEvent:
        """The single chat-message → CloudEvent mapping, shared by every chat
        connector's poll and webhook paths so their output can't drift (the
        ``id`` is an ``IngestedEvent`` primary key — dedup depends on it).

        ``source_id`` is the part after ``"{provider}:"`` in ``source`` (Slack
        uses the channel id; Discord uses ``"{guild}:{channel}"``).
        """
        data: dict[str, Any] = {
            "channel": channel_id,
            "channel_name": channel_name,
            "text": cls.clip(text),
        }
        if extra:
            data.update(extra)
        return CloudEvent(
            id=f"{provider}-{channel_id}-{message_id}",
            source=f"{provider}:{source_id}",
            type=f"com.{provider}.message",
            subject=f"channel:{channel_name}",
            time=time,
            mgtenant=org_id,
            data=data,
        )


class PollingConnector(Connector):
    """Pull: ``fetch`` a source's recent activity since a cursor."""

    @abstractmethod
    async def fetch(
        self, *, org_id: str, config: dict[str, Any], secret: str | None, since: str | None
    ) -> FetchResult: ...


class EventConnector(Connector):
    """Push: authenticate and parse a provider's inbound webhook."""

    @abstractmethod
    def verify(self, *, secret: str, headers: Mapping[str, str], body: bytes) -> bool:
        """True if the request signature is valid for ``secret``."""
        ...

    @abstractmethod
    def parse(
        self, *, headers: Mapping[str, str], body: bytes
    ) -> tuple[dict | None, list[tuple]]:
        """Turn a verified request into ``(handshake_response, dispatches)``.

        ``handshake_response`` is a dict to return verbatim for endpoint
        handshakes (Slack ``url_verification``, GitHub ``ping``), else ``None``.
        Each item in ``dispatches`` is an argument tuple forwarded as-is to the
        provider's ``service.ingest_<provider>_event(*args)``.
        """
        ...
