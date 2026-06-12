"""MCP server configuration.

The server is multi-tenant: one always-on process serves every project, and the
tenant for a request is resolved from its bearer token (signed with the shared
``JWT_SECRET``). Builder-side config (AgentFS, harness, model, DB) is read from
BuilderSettings, so the MCP server and the builder agree on the same store.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8765

    # Must match the ingest API's JWT_SECRET — that's what signs the per-project
    # MCP bearer tokens this server verifies.
    jwt_secret: str = "dev-insecure-change-me-please-set-JWT_SECRET-in-env-0123456789"
