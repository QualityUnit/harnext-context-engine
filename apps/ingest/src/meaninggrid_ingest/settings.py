"""Ingest API configuration (env-driven)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = "localhost:9092"
    database_url: str = "sqlite+aiosqlite:///./data/meaninggrid.sqlite"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # The dashboard origin (CORS + post-OAuth redirect target).
    web_origin: str = "http://localhost:3100"
    # Public base URL of this API, used to build OAuth callback URLs.
    oauth_redirect_base: str = "http://localhost:8000"

    # Auth sessions (JWT). Set a strong JWT_SECRET in production. The same secret
    # signs the per-project MCP bearer tokens (verified by the MCP server).
    jwt_secret: str = "dev-insecure-change-me-please-set-JWT_SECRET-in-env-0123456789"
    jwt_expiry_hours: int = 168  # 7 days

    # Public URL of the (multi-tenant) MCP server, shown in the Connect panel.
    mcp_public_url: str = "http://localhost:8765/mcp"

    # Self-serve signup. Off by default: this deployment is invite-only, accounts
    # are created with the `meaninggrid_ingest.admin` CLI on the server.
    registration_open: bool = False

    # Slack Events API signing secret — verifies inbound webhook POSTs. Set it to
    # enable POST /webhooks/slack (real-time messages); leave empty to disable.
    slack_signing_secret: str | None = None

    # GitHub webhook secret — verifies inbound repo webhook POSTs. Set it to
    # enable POST /webhooks/github (real-time commits/issues/PRs); empty disables.
    github_webhook_secret: str | None = None

    # OAuth apps (register your own; leave empty to disable a provider).
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None
    slack_oauth_client_id: str | None = None
    slack_oauth_client_secret: str | None = None
    # Discord — OAuth app for the bot-invite "Connect" flow + the app-level bot
    # token the poller authenticates with (one bot, invited into each guild).
    discord_oauth_client_id: str | None = None
    discord_oauth_client_secret: str | None = None
    discord_bot_token: str | None = None
    # "Sign in with Google" — Google Cloud OAuth client.
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None

    # Per-sync page sizes (keep first syncs bounded for the MVP).
    github_per_page: int = 30

    # Polling scheduler (Celery + Redis). Beat ticks every poll_beat_interval_seconds;
    # each tick claims sources whose last check is >= their interval ago (default
    # poll_default_interval_seconds) and enqueues a poll. Redis is the broker/backend.
    redis_url: str = "redis://localhost:6379/0"
    poll_default_interval_seconds: int = 3600
    poll_beat_interval_seconds: int = 60
