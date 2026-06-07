"""Produce synthetic events to the raw topic for a quick end-to-end smoke test.

No GitHub/Slack network needed. Produces a few normal commits (→ batch lane) and
one P0 issue (→ fast lane) for org `acme`, subject `repo:acme/web`.

    uv run --package meaninggrid-builder python scripts/smoke.py [org] [n_commits]

Watch the classifier route them and the builder incorporate them into the org's
AgentFS. Use MEANINGGRID_HARNESS=fake to run without an Anthropic key.
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from aiokafka import AIOKafkaProducer
from meaninggrid_shared import RAW_EVENTS_TOPIC, CloudEvent


async def main() -> None:
    org = sys.argv[1] if len(sys.argv) > 1 else "acme"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    base = datetime(2026, 6, 1, tzinfo=UTC)

    events = [
        CloudEvent(
            id=f"c{i}",
            source="github:acme/web",
            type="com.github.commit",
            subject="repo:acme/web",
            time=base + timedelta(seconds=i * 30),
            mgtenant=org,
            data={"sha": f"sha{i}", "message": f"commit {i}: refactor module", "author": "alice"},
        )
        for i in range(n)
    ]
    events.append(
        CloudEvent(
            id="i1",
            source="github:acme/web",
            type="com.github.issue",
            subject="repo:acme/web",
            time=base + timedelta(minutes=5),
            mgtenant=org,
            data={
                "number": 7,
                "title": "prod outage",
                "labels": ["P0"],
                "state": "open",
                "author": "bob",
            },
        )
    )

    producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
    await producer.start()
    try:
        for ev in events:
            await producer.send_and_wait(
                RAW_EVENTS_TOPIC, value=ev.model_dump_json().encode(), key=ev.partition_key()
            )
            print(f"produced {ev.id:8} {ev.type}")
    finally:
        await producer.stop()
    print(f"\n{len(events)} events → {RAW_EVENTS_TOPIC} (org={org})")


if __name__ == "__main__":
    asyncio.run(main())
