"""BuildRunner — incorporate one WorkItem into an org's context FS.

Flow: idempotency gate → ensure FS + record pre-snapshot → run the harness in
the mounted FS via the backend → on success: snapshot + conversation log +
ledger success; on failure: roll back to the pre-snapshot, keep the failed
transcript, ledger failed (the dispatcher then DLQs). Transactional at the
snapshot boundary: the org FS never half-absorbs an event.
"""

from __future__ import annotations

import sys
import tempfile
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from meaninggrid_builder.agentfs.store import OrgFsStore
from meaninggrid_builder.harness.base import ConversationTranscript, HarnessRequest
from meaninggrid_builder.persistence import Persistence
from meaninggrid_builder.prompts import SYSTEM_PROMPT, render_instruction
from meaninggrid_builder.settings import BuilderSettings
from meaninggrid_builder.work_item import WorkItem

# Both backends exec this with the org FS as cwd.
RUNNER_CMD = [sys.executable, "-m", "meaninggrid_builder.harness.runner"]


class BuildStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class BuildOutcome:
    status: BuildStatus
    build_id: str | None = None
    snapshot_id: str | None = None
    conversation_id: str | None = None
    error: str | None = None


class BuildRunner:
    def __init__(
        self, store: OrgFsStore, persistence: Persistence, settings: BuilderSettings
    ) -> None:
        self.store = store
        self.p = persistence
        self.s = settings

    async def run(self, wi: WorkItem) -> BuildOutcome:
        # 1. idempotency gate
        existing = await self.p.get_ledger(wi.org_id, wi.dedupe_key)
        if existing is not None and existing.status == "success":
            return BuildOutcome(
                BuildStatus.SKIPPED,
                build_id=existing.build_id,
                snapshot_id=existing.snapshot_id,
            )

        build_id = uuid.uuid4().hex
        await self.p.mark_running(wi.org_id, wi.dedupe_key, build_id, wi.lane)

        # 2. ensure FS + pre-snapshot for rollback
        await self.store.ensure(wi.org_id)
        pre = await self.store.latest_snapshot(wi.org_id)  # genesis at minimum

        # 3. render + run the harness against the mounted FS
        instruction = render_instruction(wi)
        req = HarnessRequest(
            harness=self.s.harness,
            working_dir=".",  # the runner overrides this with the mount's cwd
            instruction=instruction,
            system_prompt=SYSTEM_PROMPT,
            model=self.s.builder_model,
            max_turns=self.s.builder_max_turns,
            timeout_s=self.s.builder_timeout_s,
        )
        transcript = await self._exec(wi.org_id, req)

        # 4. commit or roll back
        if transcript is not None and transcript.ok:
            snap_id = await self.store.commit_snapshot(wi.org_id, build_id, pre.id if pre else None)
            cid = await self.p.append_conversation(
                wi.org_id, build_id, wi, transcript, instruction, snap_id
            )
            await self.p.mark_success(wi.org_id, wi.dedupe_key, build_id, snap_id)
            return BuildOutcome(BuildStatus.SUCCESS, build_id, snap_id, cid)

        if pre is not None:
            await self.store.rollback(wi.org_id, pre)
        err = (transcript.error if transcript else None) or "harness produced no result"
        stub = transcript or ConversationTranscript(
            harness=self.s.harness, stop_reason="error", error=err
        )
        cid = await self.p.append_conversation(wi.org_id, build_id, wi, stub, instruction, None)
        await self.p.mark_failed(wi.org_id, wi.dedupe_key, build_id, err[:2000])
        return BuildOutcome(BuildStatus.FAILED, build_id, None, cid, err)

    async def _exec(self, org_id: str, req: HarnessRequest) -> ConversationTranscript | None:
        with tempfile.TemporaryDirectory(prefix=f"build-{org_id}-") as tmp:
            req_path = Path(tmp) / "request.json"
            res_path = Path(tmp) / "result.json"
            req_path.write_text(req.model_dump_json())
            env = {"REQUEST_PATH": str(req_path), "RESULT_PATH": str(res_path)}
            # backend timeout slightly larger so the harness's own timeout fires first
            await self.store.run_build(org_id, RUNNER_CMD, env, req.timeout_s + 30)
            if res_path.exists():
                try:
                    return ConversationTranscript.model_validate_json(res_path.read_text())
                except ValueError:
                    return None
            return None
