"""Select a connector by source kind."""

from __future__ import annotations

from harnext_ingest.connectors.base import Connector, EventConnector

SUPPORTED_KINDS = (
    "github",
    "slack",
    "discord",
    "liveagent",
    "stripe",
    "youtube",
    "sitemap",
    "url",
)


def get_connector(kind: str, *, github_per_page: int = 30) -> Connector:
    if kind == "github":
        from harnext_ingest.connectors.github import GitHubConnector

        return GitHubConnector(per_page=github_per_page)
    if kind == "slack":
        from harnext_ingest.connectors.slack import SlackConnector

        return SlackConnector()
    if kind == "discord":
        from harnext_ingest.connectors.discord import DiscordConnector

        return DiscordConnector()
    if kind == "liveagent":
        from harnext_ingest.connectors.liveagent import LiveAgentConnector

        return LiveAgentConnector()
    if kind == "stripe":
        from harnext_ingest.connectors.stripe import StripeConnector

        return StripeConnector()
    if kind == "youtube":
        from harnext_ingest.connectors.youtube import YouTubeConnector

        return YouTubeConnector()
    if kind == "sitemap":
        from harnext_ingest.connectors.sitemap import SitemapConnector

        return SitemapConnector()
    if kind == "url":
        from harnext_ingest.connectors.url import UrlConnector

        return UrlConnector()
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
