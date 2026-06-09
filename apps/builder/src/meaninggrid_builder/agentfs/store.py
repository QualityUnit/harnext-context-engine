"""OrgFsStore — the builder/MCP-facing API over an org's context filesystem.

Wraps an FsBackend with snapshot bookkeeping in the metadata DB (FsSnapshot
rows). Only *successful* builds add a snapshot, so ``latest_snapshot`` is the
consistent, monotonic view the MCP read path mounts — never a live in-progress
build. Blocking backend (subprocess) calls run in a worker thread so the async
event loop stays free.
"""

from __future__ import annotations

import asyncio
import uuid

from meaninggrid_shared import FsSnapshot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meaninggrid_builder.agentfs.backend import FsBackend, RunResult
from meaninggrid_builder.agentfs.seed import SEED_FILES


class OrgFsStore:
    def __init__(self, backend: FsBackend, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.backend = backend
        self.sm = sessionmaker

    async def ensure(self, org_id: str) -> None:
        """Create + seed the org FS if missing, and record a genesis snapshot."""
        await asyncio.to_thread(self.backend.ensure_seeded, org_id, SEED_FILES)
        if await self.latest_snapshot(org_id) is None:
            sid = uuid.uuid4().hex
            ref = await asyncio.to_thread(self.backend.snapshot, org_id, sid)
            async with self.sm() as s:
                s.add(FsSnapshot(id=sid, org_id=org_id, kind="genesis", ref=ref))
                await s.commit()

    async def latest_snapshot(self, org_id: str) -> FsSnapshot | None:
        async with self.sm() as s:
            row = await s.execute(
                select(FsSnapshot)
                .where(FsSnapshot.org_id == org_id)
                .order_by(FsSnapshot.created_at.desc(), FsSnapshot.id.desc())
                .limit(1)
            )
            return row.scalar_one_or_none()

    async def get_snapshot(self, snapshot_id: str) -> FsSnapshot | None:
        async with self.sm() as s:
            return await s.get(FsSnapshot, snapshot_id)

    async def run_build(
        self, org_id: str, command: list[str], env: dict[str, str], timeout_s: int
    ) -> RunResult:
        """Execute a build command against the live org FS (mutates in place)."""
        return await asyncio.to_thread(self.backend.run_build, org_id, command, env, timeout_s)

    async def commit_snapshot(
        self, org_id: str, build_id: str, parent_snapshot_id: str | None
    ) -> str:
        """Capture the current FS as a new snapshot; record + return its id."""
        sid = uuid.uuid4().hex
        ref = await asyncio.to_thread(self.backend.snapshot, org_id, sid)
        async with self.sm() as s:
            s.add(
                FsSnapshot(
                    id=sid,
                    org_id=org_id,
                    build_id=build_id,
                    parent_snapshot_id=parent_snapshot_id,
                    kind="build",
                    ref=ref,
                )
            )
            await s.commit()
        return sid

    async def rollback(self, org_id: str, snapshot: FsSnapshot) -> None:
        await asyncio.to_thread(self.backend.restore, org_id, snapshot.ref)

    # -- reads --------------------------------------------------------------
    # snapshot_id=None reads the LIVE working FS. For a consistent, never-torn
    # view (the MCP read path) pass an explicit snapshot id — typically
    # ``(await latest_snapshot(org)).id`` — which reads an immutable copy
    # isolated from any concurrent build mutating the live FS.
    async def read_file(
        self, org_id: str, relpath: str, snapshot_id: str | None = None
    ) -> str | None:
        ref = await self._resolve_ref(snapshot_id)
        return await asyncio.to_thread(self.backend.read_file, org_id, relpath, ref)

    async def list_files(self, org_id: str, snapshot_id: str | None = None) -> list[str]:
        ref = await self._resolve_ref(snapshot_id)
        return await asyncio.to_thread(self.backend.list_files, org_id, ref)

    # -- writes -------------------------------------------------------------
    async def write_file(self, org_id: str, relpath: str, content: str) -> str:
        """Write one file to the live FS and capture it as a new ``edit``
        snapshot; return the new snapshot id.

        The snapshot is what makes a manual edit safe and visible: it becomes
        the new ``latest_snapshot`` — the consistent view the MCP read path
        mounts *and* the rollback floor for the next build, so a later failed
        build can't silently discard the edit (BuildRunner rolls back to the
        latest snapshot taken before it ran)."""
        await self.ensure(org_id)
        await asyncio.to_thread(self.backend.write_file, org_id, relpath, content)
        parent = await self.latest_snapshot(org_id)
        sid = uuid.uuid4().hex
        ref = await asyncio.to_thread(self.backend.snapshot, org_id, sid)
        async with self.sm() as s:
            s.add(
                FsSnapshot(
                    id=sid,
                    org_id=org_id,
                    parent_snapshot_id=parent.id if parent else None,
                    kind="edit",
                    ref=ref,
                )
            )
            await s.commit()
        return sid

    async def _resolve_ref(self, snapshot_id: str | None) -> str | None:
        if snapshot_id is None:
            return None  # live working copy
        snap = await self.get_snapshot(snapshot_id)
        return snap.ref if snap else None
