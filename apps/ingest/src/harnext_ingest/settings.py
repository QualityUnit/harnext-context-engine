"""Ingest API configuration (env-driven)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = "localhost:9092"
    database_url: str = "sqlite+aiosqlite:///./data/harnext.sqlite"

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

    # -- Agent harness OAuth (RFC 8628 device flow) + pushed conversation logs --
    # Harness CLIs are public OAuth clients; the security boundary is the human
    # approval step in the dashboard, so a single static public client id is fine.
    agent_oauth_client_id: str = "harnext-cli"
    agent_access_token_ttl_seconds: int = 3600  # short-lived access token (1h)
    agent_refresh_token_ttl_days: int = 90  # 0 = non-expiring refresh token
    device_code_ttl_seconds: int = 600  # RFC 8628 expires_in for the device code
    device_poll_interval_seconds: int = 5  # RFC 8628 interval (slow_down floor)
    # Per-event payload cap for pushed conversation turns (like McpRequest sizing).
    agent_event_max_bytes: int = 65536
    # Max turns accepted in a single append batch (bounds one POST).
    agent_event_max_batch: int = 200

    # Self-serve signup. Off by default: this deployment is invite-only, accounts
    # are created with the `harnext_ingest.admin` CLI on the server.
    registration_open: bool = False

    # -- Closed-beta / webinar registration (Mailchimp) --------------------
    # While Harnext isn't generally available, the "register" page collects
    # interested users' name + email and tags them in an existing Mailchimp
    # audience (no new audience, no local storage). Set the API key to enable
    # POST /beta/signup; leave empty and the endpoint returns 503.
    mailchimp_api_key: str | None = None
    mailchimp_audience_id: str = "485db66a95"
    mailchimp_beta_tag: str = "harnext-closed-beta"

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
    # poll_default_interval_seconds) and enqueues a poll. Redis is the broker/backend
    # (shared by the website crawl tasks below).
    redis_url: str = "redis://localhost:6379/0"
    poll_default_interval_seconds: int = 3600
    poll_beat_interval_seconds: int = 60

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
    crawl_user_agent: str = "HarnextBot/1.0 (+https://harnext.dev/bot)"
    # Celery per-worker ceiling for the fan-out crawl_url task (e.g. "30/m").
    # The hard guarantee a sitemap with thousands of URLs can't flood the origin.
    crawl_rate_limit: str = "30/m"
