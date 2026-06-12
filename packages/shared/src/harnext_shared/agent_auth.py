"""Tokens + codes for the agent-harness OAuth surface (RFC 8628 device flow).

A harness CLI is a *public* OAuth client (it can't keep a secret), so the
security boundary is the human approval step in the dashboard — not client
authentication. Once approved, the engine issues:

  - a short-lived **access token**: a JWT signed with the deployment's shared
    ``JWT_SECRET`` (same secret as session/MCP tokens), scoped ``agent`` and
    carrying the granted ``org`` + approving ``sub``. The ``scope`` claim keeps
    it from being usable as a session or MCP token (and vice-versa).
  - a long-lived **refresh token**: an opaque random string returned once to the
    client; only its SHA-256 hash is stored (high-entropy → a fast hash with
    exact-match lookup is correct). Rotated on every use.

Both the ingest API (which mints) and any verifier import these helpers, so the
claim shape can never drift between the two sides — mirroring ``mcp_auth.py``.
"""

from __future__ import annotations

import hashlib
import secrets
import time

import jwt

_ALGO = "HS256"
_SCOPE = "agent"

# User-code alphabet: unambiguous (no 0/O, 1/I/L) so it's easy to read + type.
_USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ23456789"


def create_agent_access_token(org_id: str, user_id: str, secret: str, ttl_seconds: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"org": org_id, "sub": user_id, "scope": _SCOPE, "iat": now, "exp": now + ttl_seconds},
        secret,
        algorithm=_ALGO,
    )


def decode_agent_access_token(token: str, secret: str) -> dict | None:
    """Return ``{"org", "sub"}`` for a valid, unexpired agent access token, or
    ``None`` if it isn't one for this secret (wrong scope, bad signature, expired)."""
    try:
        claims = jwt.decode(token, secret, algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None
    if claims.get("scope") != _SCOPE:
        return None
    org = claims.get("org")
    sub = claims.get("sub")
    if not (isinstance(org, str) and org and isinstance(sub, str) and sub):
        return None
    return {"org": org, "sub": sub}


def hash_refresh_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Return ``(plaintext, sha256_hex)``. The plaintext is returned to the client
    exactly once; only the hash is persisted."""
    plaintext = secrets.token_urlsafe(32)
    return plaintext, hash_refresh_token(plaintext)


def new_device_code() -> str:
    return secrets.token_urlsafe(32)


def new_user_code() -> str:
    """A short, human-typable code grouped as ``XXXX-XXXX`` from an unambiguous
    alphabet."""
    raw = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"
