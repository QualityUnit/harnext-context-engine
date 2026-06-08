"""Bearer tokens for the MCP surface — a per-project connect token.

The token is a JWT signed with the deployment's shared ``JWT_SECRET`` and carries
the project's org id with a fixed ``mcp`` scope. It is intentionally deterministic
and non-expiring (no ``iat``/``exp``) so the dashboard can show one stable
"paste once" value per project; revoke by rotating ``JWT_SECRET``.

Both the ingest API (which mints the token) and the MCP server (which verifies it
and resolves the per-request tenant) import these helpers, so the claim shape can
never drift between the two sides.
"""

from __future__ import annotations

import jwt

_ALGO = "HS256"
_SCOPE = "mcp"


def create_mcp_token(org_id: str, secret: str) -> str:
    return jwt.encode({"org": org_id, "scope": _SCOPE}, secret, algorithm=_ALGO)


def decode_mcp_token(token: str, secret: str) -> str | None:
    """Return the org id a token is scoped to, or ``None`` if it isn't a valid
    MeaningGrid MCP token for this secret."""
    try:
        claims = jwt.decode(token, secret, algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None
    if claims.get("scope") != _SCOPE:
        return None
    org = claims.get("org")
    return org if isinstance(org, str) and org else None
