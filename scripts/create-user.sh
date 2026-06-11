#!/usr/bin/env bash
# Create a Harnext account on this server (registration is invite-only).
#
#   ./scripts/create-user.sh <email> [name]
#
# Prompts for the password (hidden) and pipes it to the ingest container over
# stdin — it never appears in argv, env, or shell history.
set -euo pipefail

EMAIL="${1:-}"
NAME="${2:-}"
if [ -z "$EMAIL" ]; then
  echo "usage: $0 <email> [name]" >&2
  exit 1
fi

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.prod.yml"

read -rs -p "Password (min 6 chars): " PW; echo
read -rs -p "Confirm password: " PW2; echo
[ "$PW" = "$PW2" ] || { echo "passwords do not match" >&2; exit 1; }

set -- create-user --email "$EMAIL" --password-stdin
[ -n "$NAME" ] && set -- "$@" --name "$NAME"

printf '%s\n' "$PW" | $COMPOSE exec -T ingest python -m harnext_ingest.admin "$@"
