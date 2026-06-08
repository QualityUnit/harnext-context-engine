#!/bin/sh
# Seed the Claude Code OAuth credentials into a persistent ~/.claude on first
# boot, so the headless `claude` CLI (used by the builder/mcp harness) is
# authenticated via your account token — no ANTHROPIC_API_KEY needed.
#
# - /run/secrets/claude-credentials.json : read-only seed (your local token)
# - $HOME/.claude                        : a named volume, so the CLI's token
#                                          refreshes persist across restarts.
set -e

SEED=/run/secrets/claude-credentials.json
DEST="$HOME/.claude/.credentials.json"

if [ -f "$SEED" ] && [ ! -f "$DEST" ]; then
  mkdir -p "$HOME/.claude"
  cp "$SEED" "$DEST"
  chmod 600 "$DEST"
  echo "entrypoint: seeded Claude credentials at $DEST"
fi

exec "$@"
