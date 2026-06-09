"""Builder configuration (env-driven)."""

from pydantic import AliasChoices, Field
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

    # Harnext harness (MEANINGGRID_HARNESS=harnext): routes the harnext CLI at a
    # provider/model. The key is read from any of the aliased env vars and handed
    # to the CLI subprocess under `harnext_api_key_env` (the name the provider
    # reads — NVIDIA NIM → NVIDIA_API_KEY, OpenRouter → OPENROUTER_API_KEY).
    # `harnext_model` overrides builder_model so the same deployment can run Claude
    # on one harness and an OpenRouter model on this one.
    harnext_provider: str | None = Field(default=None, validation_alias="HARNEXT_PROVIDER")
    harnext_model: str | None = Field(default=None, validation_alias="HARNEXT_MODEL")
    harnext_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "HARNEXT_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_NIM_API_KEY", "NVIDIA_API_KEY"
        ),
    )
    harnext_api_key_env: str = Field(default="NVIDIA_API_KEY", validation_alias="HARNEXT_API_KEY_ENV")
    harnext_permission_mode: str = Field(
        default="dontAsk", validation_alias="HARNEXT_PERMISSION_MODE"
    )

    # Concurrency: different orgs build in parallel up to this; one org is serial.
    max_concurrent_builds: int = 4
