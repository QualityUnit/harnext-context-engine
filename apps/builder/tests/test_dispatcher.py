"""Dispatcher serialization + DLQ, and lane decode."""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime

from harnext_builder.build_runner import BuildOutcome, BuildStatus
from harnext_builder.consumer import decode
from harnext_builder.dispatcher import Dispatcher
from harnext_builder.work_item import WorkItem
from harnext_shared import CloudEvent, ContextUnit


def _ev(eid, org="acme"):
    return CloudEvent(
        id=eid,
        source="github:acme/web",
        type="com.github.commit",
        subject="repo:acme/web",
        time=datetime.now(UTC),
        mgtenant=org,
        data={},
    )


class _FakeRunner:
    def __init__(self, status=BuildStatus.SUCCESS):
        self.status = status
        self.org_active: dict[str, int] = defaultdict(int)
        self.org_max: dict[str, int] = defaultdict(int)
        self.global_active = 0
        self.global_max = 0

    async def run(self, wi: WorkItem) -> BuildOutcome:
        self.org_active[wi.org_id] += 1
        self.global_active += 1
        self.org_max[wi.org_id] = max(self.org_max[wi.org_id], self.org_active[wi.org_id])
        self.global_max = max(self.global_max, self.global_active)
        await asyncio.sleep(0.05)
        self.org_active[wi.org_id] -= 1
        self.global_active -= 1
        return BuildOutcome(
            self.status, build_id="b", error="boom" if self.status is BuildStatus.FAILED else None
        )


class _FakeDlq:
    def __init__(self):
        self.sent = []

    async def send(self, wi, error):
        self.sent.append((wi, error))


async def test_same_org_serialized():
    runner, dlq = _FakeRunner(), _FakeDlq()
    d = Dispatcher(runner, dlq, max_concurrent=4)
    await asyncio.gather(
        d.submit(WorkItem.from_fast_event(_ev("a", "acme"))),
        d.submit(WorkItem.from_fast_event(_ev("b", "acme"))),
    )
    assert runner.org_max["acme"] == 1  # never two builds for one org at once


async def test_different_orgs_concurrent():
    runner, dlq = _FakeRunner(), _FakeDlq()
    d = Dispatcher(runner, dlq, max_concurrent=4)
    await asyncio.gather(
        d.submit(WorkItem.from_fast_event(_ev("a", "org1"))),
        d.submit(WorkItem.from_fast_event(_ev("b", "org2"))),
    )
    assert runner.global_max == 2  # distinct orgs overlap


async def test_concurrency_capped():
    runner, dlq = _FakeRunner(), _FakeDlq()
    d = Dispatcher(runner, dlq, max_concurrent=2)
    await asyncio.gather(
        *(d.submit(WorkItem.from_fast_event(_ev(str(i), f"org{i}"))) for i in range(5))
    )
    assert runner.global_max <= 2


async def test_failed_build_goes_to_dlq():
    runner, dlq = _FakeRunner(BuildStatus.FAILED), _FakeDlq()
    d = Dispatcher(runner, dlq, max_concurrent=2)
    wi = WorkItem.from_fast_event(_ev("x", "acme"))
    await d.submit(wi)
    assert len(dlq.sent) == 1 and dlq.sent[0][0].dedupe_key == wi.dedupe_key


def test_decode_fast_and_batch():
    ev = _ev("e1")
    wi = decode("fast", ev.model_dump_json().encode())
    assert wi is not None and wi.lane == "fast" and wi.events[0].id == "e1"

    cu = ContextUnit(
        org_id="acme",
        subject="repo:acme/web",
        window_id="w1",
        window_start=ev.time,
        window_end=ev.time,
        events=[ev],
    )
    wb = decode("batch", cu.model_dump_json(by_alias=True).encode())
    assert wb is not None and wb.lane == "batch" and wb.dedupe_key == "w1" and len(wb.events) == 1

    assert decode("fast", b"not json") is None
