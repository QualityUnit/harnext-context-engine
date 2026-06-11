"""Builder persistence: the BuildLedger (idempotency) + the URL-addressable
raw-conversation log. Both live in the shared metadata DB."""

from __future__ import annotations

import json
import uuid

from harnext_shared import BuildLedger, ConversationLog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harnext_builder.harness.base import ConversationTranscript
from harnext_builder.work_item import WorkItem


class Persistence:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sm = sessionmaker

    # -- ledger ------------------------------------------------------------
    async def get_ledger(self, org_id: str, dedupe_key: str) -> BuildLedger | None:
        async with self.sm() as s:
            return await s.get(BuildLedger, (org_id, dedupe_key))

    async def mark_running(self, org_id: str, dedupe_key: str, build_id: str, lane: str) -> None:
        async with self.sm() as s:
            row = await s.get(BuildLedger, (org_id, dedupe_key))
            if row is None:
                s.add(
                    BuildLedger(
                        org_id=org_id,
                        dedupe_key=dedupe_key,
                        build_id=build_id,
                        lane=lane,
                        status="running",
                        attempts=1,
                    )
                )
            else:
                row.status = "running"
                row.build_id = build_id
                row.attempts += 1
                row.last_error = None
            await s.commit()

    async def mark_success(
        self, org_id: str, dedupe_key: str, build_id: str, snapshot_id: str
    ) -> None:
        await self._finish(org_id, dedupe_key, build_id, "success", snapshot_id, None)

    async def mark_failed(self, org_id: str, dedupe_key: str, build_id: str, error: str) -> None:
        await self._finish(org_id, dedupe_key, build_id, "failed", None, error)

    async def _finish(
        self,
        org_id: str,
        dedupe_key: str,
        build_id: str,
        status: str,
        snapshot_id: str | None,
        error: str | None,
    ) -> None:
        async with self.sm() as s:
            row = await s.get(BuildLedger, (org_id, dedupe_key))
            if row is not None:
                row.status = status
                row.build_id = build_id
                row.snapshot_id = snapshot_id
                row.last_error = error
                await s.commit()

    # -- conversation log --------------------------------------------------
    async def append_conversation(
        self,
        org_id: str,
        build_id: str,
        wi: WorkItem,
        transcript: ConversationTranscript,
        instruction: str,
        snapshot_id: str | None,
    ) -> str:
        cid = uuid.uuid4().hex
        async with self.sm() as s:
            s.add(
                ConversationLog(
                    id=cid,
                    org_id=org_id,
                    build_id=build_id,
                    dedupe_key=wi.dedupe_key,
                    lane=wi.lane,
                    harness=transcript.harness,
                    model=transcript.model,
                    instruction=instruction,
                    transcript_json=transcript.model_dump_json(),
                    files_changed_json=json.dumps(transcript.files_changed),
                    usage_json=json.dumps(transcript.usage, default=str),
                    stop_reason=transcript.stop_reason,
                    snapshot_id=snapshot_id,
                )
            )
            await s.commit()
        return cid
