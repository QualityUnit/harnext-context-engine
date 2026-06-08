#!/bin/sh
# Runs as root only long enough to prepare the mounted volumes, then drops to
# the non-root `app` user (Claude Code refuses --dangerously-skip-permissions as
# root). Seeds the Claude OAuth credentials into a persistent ~/.claude so the
# headless CLI is authenticated via your account token — no ANTHROPIC_API_KEY.
#
# - /run/secrets/claude-credentials.json : read-only seed (your local token)
# - /home/app/.claude                    : named volume (token refreshes persist)
# - /app/data                            : shared sqlite + agentfs volume
set -e

APP_HOME=/home/app
SEED=/run/secrets/claude-credentials.json

mkdir -p "$APP_HOME/.claude" /app/data

if [ -f "$SEED" ] && [ ! -f "$APP_HOME/.claude/.credentials.json" ]; then
  cp "$SEED" "$APP_HOME/.claude/.credentials.json"
  echo "entrypoint: seeded Claude credentials"
fi

# The volumes mount root-owned on first use; hand them to the app user.
chown -R app:app "$APP_HOME/.claude" /app/data 2>/dev/null || true
chmod 600 "$APP_HOME/.claude/.credentials.json" 2>/dev/null || true

exec gosu app "$@"
