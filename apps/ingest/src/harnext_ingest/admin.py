"""Admin CLI — create accounts on an invite-only instance (no self-serve signup).

Run inside the ingest container so it shares the same database:

    docker compose -f docker-compose.prod.yml exec -T ingest \\
        python -m harnext_ingest.admin create-user --email you@org.com --name "You" --password-stdin

The password is read from stdin (so it never lands in argv / shell history); see
scripts/create-user.sh for the convenience wrapper.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from harnext_shared import CloudEvent, init_db, make_engine, make_sessionmaker

from harnext_ingest.service import SourceService
from harnext_ingest.settings import IngestSettings


class _NullProducer:
    async def send_event(self, topic: str, event: CloudEvent) -> None:  # pragma: no cover
        return None


async def _create_user(email: str, password: str, name: str | None) -> int:
    settings = IngestSettings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    svc = SourceService(make_sessionmaker(engine), _NullProducer(), settings)
    try:
        user = await svc.register(email.strip().lower(), password, name)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    print(f"created user {user.id}  <{user.email}>")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="harnext-admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user", help="create a dashboard account")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", default=None)
    g = cu.add_mutually_exclusive_group()
    g.add_argument("--password", help="(insecure: visible in argv) the password")
    g.add_argument(
        "--password-stdin", action="store_true", help="read the password from stdin"
    )
    args = parser.parse_args()

    if args.cmd == "create-user":
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\n")
        elif args.password:
            password = args.password
        else:
            password = getpass.getpass("Password: ")
        if len(password) < 6:
            print("error: password must be at least 6 characters", file=sys.stderr)
            raise SystemExit(1)
        raise SystemExit(asyncio.run(_create_user(args.email, password, args.name)))


if __name__ == "__main__":
    main()
