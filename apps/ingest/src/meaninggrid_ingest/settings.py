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

    # OAuth apps (register your own; leave empty to disable a provider's Connect button).
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None
    slack_oauth_client_id: str | None = None
    slack_oauth_client_secret: str | None = None

    # Per-sync page sizes (keep first syncs bounded for the MVP).
    github_per_page: int = 30
