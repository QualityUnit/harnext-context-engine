"""Init script — creates tables + seeds a default tenant.

Usage: `uv run --package meaninggrid-api python -m meaninggrid_api.bootstrap`
"""

import asyncio
import logging
import sys

from sqlalchemy import select

from meaninggrid_api.db import SessionLocal, init_models
from meaninggrid_api.storage import ensure_bucket
from meaninggrid_shared import Tenant

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("meaninggrid.bootstrap")

DEFAULT_TENANT_ID = "default"
DEFAULT_TENANT_NAME = "Default Tenant"


async def main() -> None:
    log.info("creating tables …")
    await init_models()

    log.info("ensuring MinIO bucket …")
    try:
        await ensure_bucket()
    except Exception as e:
        log.warning("could not ensure bucket (is MinIO up?): %s", e)

    log.info("seeding default tenant '%s' …", DEFAULT_TENANT_ID)
    async with SessionLocal() as session:
        existing = await session.scalar(select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID))
        if existing is None:
            session.add(Tenant(id=DEFAULT_TENANT_ID, name=DEFAULT_TENANT_NAME))
            await session.commit()
            log.info("seeded.")
        else:
            log.info("default tenant already exists; skipping seed.")

    log.info("bootstrap complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
