"""Classifier configuration (env-driven)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ClassifierSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = "localhost:9092"
    database_url: str = "sqlite+aiosqlite:///./data/harnext.sqlite"

    # Per-entity anomaly scorer (MVP: Welford z on inter-arrival gap).
    anomaly_threshold: float = 3.0
    anomaly_min_samples: int = 5

    # Batch session windows (per entity).
    window_gap_s: float = 30.0  # close after this much inactivity
    window_max_events: int = 20  # close once a window reaches this many events
    window_max_age_s: float = 120.0  # hard cap on window age
    window_sweep_s: float = 5.0  # how often the sweeper checks for due windows
