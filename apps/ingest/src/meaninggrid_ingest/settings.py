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

    # -- Sitemap connector / web crawler -----------------------------------
    # Politeness budget for the website crawler so a connected site is never
    # overwhelmed. Per-source overrides may be passed in the source config.
    # The Celery crawler covers ALL pages (throttled by crawl_rate_limit);
    # crawl_max_pages bounds only the inline-sync connection test (oldest-first).
    crawl_max_pages: int = 50  # inline-sync page cap; Celery fan-out is uncapped
    crawl_delay_seconds: float = 1.0  # pause before each page request
    crawl_concurrency: int = 4  # max simultaneous in-flight requests (inline path)
    crawl_timeout_seconds: float = 20.0  # per-request timeout
    crawl_max_bytes: int = 2_000_000  # response body read cap
    crawl_respect_robots: bool = True  # honour robots.txt (skip disallowed pages)
    crawl_user_agent: str = "MeaningGridBot/1.0 (+https://meaninggrid.dev/bot)"
    # Celery per-worker ceiling for the fan-out crawl_url task (e.g. "30/m").
    # The hard guarantee a sitemap with thousands of URLs can't flood the origin.
    crawl_rate_limit: str = "30/m"

    # -- Celery (distributed crawl scheduling) -----------------------------
    # Shared with the polling scheduler. Redis broker by default; the worker is
    # `celery -A meaninggrid_ingest.celery_app worker`.
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
