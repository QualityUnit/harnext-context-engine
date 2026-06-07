"""Ingest API configuration (env-driven)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = "localhost:9092"
    database_url: str = "sqlite+aiosqlite:///./data/meaninggrid.sqlite"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # CORS origin for the Next.js dev UI.
    web_origin: str = "http://localhost:3100"

    # Per-sync page sizes (keep first syncs bounded for the MVP).
    github_per_page: int = 30
