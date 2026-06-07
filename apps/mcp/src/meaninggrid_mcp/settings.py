"""MCP server configuration. One org per instance (the tenant boundary).

Builder-side config (AgentFS, harness, model, DB) is read from BuilderSettings,
so the MCP server and the builder agree on the same store and harness.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    org_id: str = Field(default="acme", validation_alias="MEANINGGRID_ORG_ID")
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8765
