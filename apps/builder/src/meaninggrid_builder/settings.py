"""Builder configuration (env-driven)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BuilderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"

    # Control-plane / metadata store
    database_url: str = "sqlite+aiosqlite:///./data/meaninggrid.sqlite"

    # AgentFS store
    agentfs_dir: str = "./data/agentfs"
    agentfs_backend: str = "agentfs"  # agentfs | git
    agentfs_bin: str = "agentfs"

    # Harness
    harness: str = Field(default="claude_code", validation_alias="MEANINGGRID_HARNESS")
    anthropic_api_key: str | None = None
    builder_model: str = "claude-sonnet-4-6"
    builder_max_turns: int = 40
    builder_timeout_s: int = 300

    # Concurrency: different orgs build in parallel up to this; one org is serial.
    max_concurrent_builds: int = 4
