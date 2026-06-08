"""Smoke-test the LiveAgent connector against a real install — no Kafka/Redis/web.

Reads credentials from the environment so nothing secret is passed on the CLI:

    export LIVEAGENT_BASE_URL="https://yourcompany.ladesk.com"
    export LIVEAGENT_API_KEY="your-v3-api-key"
    # optional — narrow what we walk:
    export LIVEAGENT_DEPARTMENT="<department id>"   # from the listing below
    export LIVEAGENT_TAG="<tag id>"                 # optional

    uv run --package meaninggrid-ingest python scripts/smoke_liveagent.py

With no LIVEAGENT_DEPARTMENT set it just lists departments + tags so you can grab
an id, then re-run with that id to walk a page of tickets and watch the cursor
advance (it fetches twice, feeding the first cursor back into the second call).
"""

from __future__ import annotations

import asyncio
import os
import sys

from meaninggrid_ingest.connectors.liveagent import (
    LiveAgentConnector,
    list_departments,
    list_tags,
    normalize_base_url,
)


async def main() -> int:
    base = os.environ.get("LIVEAGENT_BASE_URL")
    key = os.environ.get("LIVEAGENT_API_KEY")
    if not base or not key:
        print("set LIVEAGENT_BASE_URL and LIVEAGENT_API_KEY in the environment", file=sys.stderr)
        return 2
    base = normalize_base_url(base)
    print(f"→ base URL: {base}\n")

    print("departments:")
    depts = await list_departments(base, key)
    for d in depts:
        print(f"  {d['id']:>16}  {d['name']}")
    print(f"\ntags: ({len(await list_tags(base, key))} found)")
    for t in await list_tags(base, key):
        print(f"  {t['id']:>16}  {t['name']}")

    dept = os.environ.get("LIVEAGENT_DEPARTMENT")
    if not dept:
        print("\nset LIVEAGENT_DEPARTMENT=<id from above> and re-run to walk its tickets.")
        return 0

    tag = os.environ.get("LIVEAGENT_TAG") or None
    dept_name = next((d["name"] for d in depts if d["id"] == dept), dept)
    config = {"base_url": base, "department_id": dept, "department_name": dept_name}
    if tag:
        config["tag_id"] = tag
    connector = LiveAgentConnector(per_poll=10)  # small page so the smoke test is quick

    print(f"\n── walking department {dept_name!r}{' tag ' + tag if tag else ''} ──")
    cursor = None
    for sync_no in (1, 2):
        res = await connector.fetch(org_id="smoke", config=config, secret=key, since=cursor)
        print(f"\nsync #{sync_no}: {len(res.events)} ticket(s)  (since={cursor!r})")
        for e in res.events:
            body = (e.data.get("body") or "").replace("\n", " ")
            print(f"  [{e.data['ticket_id']}] {e.data.get('title')!r}  ·  {e.time.isoformat()}")
            if body:
                print(f"        {body[:120]}{'…' if len(body) > 120 else ''}")
        print(f"  cursor → {res.cursor!r}")
        if res.cursor == cursor:
            print("  (cursor unchanged — caught up)")
            break
        cursor = res.cursor
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
