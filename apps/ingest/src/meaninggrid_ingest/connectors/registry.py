"""Select a connector by source kind."""

from __future__ import annotations

from meaninggrid_ingest.connectors.base import Connector, EventConnector

SUPPORTED_KINDS = ("github", "slack", "discord", "youtube")


def get_connector(kind: str, *, github_per_page: int = 30) -> Connector:
    if kind == "github":
        from meaninggrid_ingest.connectors.github import GitHubConnector

        return GitHubConnector(per_page=github_per_page)
    if kind == "slack":
        from meaninggrid_ingest.connectors.slack import SlackConnector

        return SlackConnector()
    if kind == "discord":
        from meaninggrid_ingest.connectors.discord import DiscordConnector

        return DiscordConnector()
    if kind == "youtube":
        from meaninggrid_ingest.connectors.youtube import YouTubeConnector

        return YouTubeConnector()
    raise ValueError(f"unknown source kind: {kind!r}")


def event_connector(kind: str) -> EventConnector | None:
    """The EventConnector for a provider that delivers signed webhooks, or None.

    Used by the ``/webhooks/{provider}`` routes; polling-only kinds (e.g.
    discord) return None."""
    try:
        c = get_connector(kind)
    except ValueError:
        return None
    return c if isinstance(c, EventConnector) else None
