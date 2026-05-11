"""Tenant context — v0 uses an X-Tenant-Id header.

Real auth (SSO / JWT / sessions) gets its own doc and replaces this file.
The contract — `get_tenant_id() -> str` as a FastAPI dependency — stays
the same so endpoints don't change when auth is upgraded.
"""

from fastapi import Header, HTTPException, status


async def get_tenant_id(x_tenant_id: str | None = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Tenant-Id header (v0 auth stub).",
        )
    return x_tenant_id
