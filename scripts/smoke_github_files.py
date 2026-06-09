"""Live smoke test for GitHub changed-file materialization.

Produces a synthetic GitHub *commit* event whose ``data["files"]`` carries real
file content to the raw topic, then watches the pipeline carry it through:

    raw → classifier → fast/batch → builder → agent reads `_event/` → org FS

    uv run --package meaninggrid-builder python scripts/smoke_github_files.py [org]

Run the stack first (`make up`, then the classifier + builder, or docker-compose).
Use MEANINGGRID_HARNESS=fake to run without an Anthropic key — the fake harness
folds the `_event/` files it sees into `_meta/last_build.md`, so you can confirm
the agent actually had access:

    agentfs fs ./data/agentfs/.agentfs/<org>.db cat _meta/last_build.md

With MEANINGGRID_HARNESS=claude_code, inspect the entity OVERVIEW/timeline the
agent wrote — it should reflect what the changed file actually did, not just the
commit message.
"""

import asyncio
import sys
from datetime import UTC, datetime

from aiokafka import AIOKafkaProducer
from meaninggrid_shared import RAW_EVENTS_TOPIC, CloudEvent

_APP_PY = '''\
def charge(amount_cents: int, currency: str = "usd") -> dict:
    # NEW: enforce a hard ceiling so a fat-fingered amount can't go through
    if amount_cents > 1_000_000:
        raise ValueError("amount exceeds $10,000 ceiling")
    return {"amount": amount_cents, "currency": currency, "status": "ok"}
'''


async def main() -> None:
    org = sys.argv[1] if len(sys.argv) > 1 else "acme"
    ev = CloudEvent(
        id="github-commit-acme/web-smoke1",
        source="github:acme/web",
        type="com.github.commit",
        subject="repo:acme/web",
        time=datetime(2026, 6, 10, tzinfo=UTC),
        mgtenant=org,
        data={
            "sha": "smoke1",
            "message": "billing: enforce a $10k charge ceiling",
            "author": "alice",
            "url": "https://github.com/acme/web/commit/smoke1",
            "files": [
                {"path": "billing/app.py", "status": "modified", "content": _APP_PY},
                {"path": "billing/legacy.py", "status": "removed"},
            ],
        },
    )

    producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
    await producer.start()
    try:
        await producer.send_and_wait(
            RAW_EVENTS_TOPIC, value=ev.model_dump_json().encode(), key=ev.partition_key()
        )
        print(f"produced {ev.id} ({ev.type}) with {len(ev.data['files'])} changed file(s) → {RAW_EVENTS_TOPIC}")
        print(f"org={org}: watch the builder write the org FS; the agent should read billing/app.py from _event/")
    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
