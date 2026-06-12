"""Startup reconciliation.

A crash mid-build can leave an org's live FS partially edited and a BuildLedger
row stuck at ``running``. On startup we roll every org's live FS back to its
latest committed snapshot (discarding partial edits) and mark orphaned
``running`` rows ``failed`` so redelivery re-runs them cleanly (the dedupe gate
only skips ``success``). Restoring is idempotent after a clean shutdown.
"""

from __future__ import annotations

import logging

from harnext_shared import BuildLedger, FsSnapshot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harnext_builder.agentfs.store import OrgFsStore

log = logging.getLogger("builder.reconcile")


async def reconcile(store: OrgFsStore, sm: async_sessionmaker[AsyncSession]) -> None:
    async with sm() as s:
        orgs = list((await s.execute(select(FsSnapshot.org_id).distinct())).scalars())
    for org in orgs:
        latest = await store.latest_snapshot(org)
        if latest is not None:
            await store.rollback(org, latest)
            log.info("reconciled org=%s → snapshot %s", org, latest.id)

    async with sm() as s:
        orphans = list(
            (await s.execute(select(BuildLedger).where(BuildLedger.status == "running"))).scalars()
        )
        for row in orphans:
            row.status = "failed"
            row.last_error = "orphaned at startup (build did not complete)"
        if orphans:
            await s.commit()
            log.info("marked %d orphaned running build(s) as failed", len(orphans))
