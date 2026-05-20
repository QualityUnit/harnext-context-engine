from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Single-tenant by env (matches the v0 X-Tenant-Id stub in apps/api).
    tenant_id: str = Field(default="", validation_alias="MEANINGGRID_TENANT_ID")

    falkordb_host: str = "localhost"
    # 6380 matches infra/docker-compose.yml host-port mapping (container 6379).
    falkordb_port: int = 6380
    falkordb_username: str = ""
    falkordb_password: str = ""

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8765

    # Defensive caps — keep agents from melting the graph or our context window.
    mcp_cypher_timeout_ms: int = 15_000
    mcp_max_rows: int = 500


settings = Settings()
