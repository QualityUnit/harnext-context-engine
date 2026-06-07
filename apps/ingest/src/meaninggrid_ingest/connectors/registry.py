"""Select a connector by source kind."""

from __future__ import annotations

from meaninggrid_ingest.connectors.base import Connector

SUPPORTED_KINDS = ("github", "slack")


def get_connector(kind: str, *, github_per_page: int = 30) -> Connector:
    if kind == "github":
        from meaninggrid_ingest.connectors.github import GitHubConnector

        return GitHubConnector(per_page=github_per_page)
    if kind == "slack":
        from meaninggrid_ingest.connectors.slack import SlackConnector

        return SlackConnector()
    raise ValueError(f"unknown source kind: {kind!r}")
