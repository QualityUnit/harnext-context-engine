"""Smoke-test the harnext harness against OpenRouter (real network call).

Exercises the full builder path — BuilderSettings → HarnextHarness → harnext_sdk
→ the `harnext` CLI → OpenRouter — by pointing the agent at a throwaway working
dir and asking it to create one file, then asserting the file landed and the run
reported success.

Requires the harnext CLI (>=1.5, OpenRouter support) on PATH (`npm i -g harnext`)
and an OpenRouter key. Provide the key via env or the repo-root .env:

    HARNEXT_PROVIDER=openrouter
    HARNEXT_MODEL=anthropic/claude-sonnet-4.5
    HARNEXT_API_KEY_ENV=OPENROUTER_API_KEY
    OPENROUTER_API_KEY=sk-or-...

Run:

    OPENROUTER_API_KEY=sk-or-... \
      uv run --package harnext-builder python scripts/smoke_harnext_openrouter.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from harnext_builder.harness.base import HarnessRequest
from harnext_builder.harness.harnext import HarnextHarness
from harnext_builder.settings import BuilderSettings

_MARKER = "harnext-openrouter-ok"


async def main() -> int:
    s = BuilderSettings()
    # Default to OpenRouter so the script is runnable with just OPENROUTER_API_KEY set.
    if not s.harnext_provider:
        s.harnext_provider = "openrouter"
    if not s.harnext_model:
        s.harnext_model = "anthropic/claude-sonnet-4.5"
    if s.harnext_provider == "openrouter" and s.harnext_api_key_env == "NVIDIA_API_KEY":
        s.harnext_api_key_env = "OPENROUTER_API_KEY"

    if not s.harnext_api_key:
        print(
            "No OpenRouter key found. Set OPENROUTER_API_KEY (in the repo-root .env "
            "or the environment) and re-run.",
            file=sys.stderr,
        )
        return 2

    with tempfile.TemporaryDirectory(prefix="harnext-or-") as d:
        req = HarnessRequest(
            harness="harnext",
            working_dir=d,
            instruction=(
                f"Create a file named result.txt in the current directory whose only "
                f"contents are exactly: {_MARKER}"
            ),
            system_prompt="You are a terse coding agent. Do exactly what is asked, then stop.",
            max_turns=6,
            timeout_s=120,
        )

        print(f"provider={s.harnext_provider} model={s.harnext_model} cwd={d}")
        t = await HarnextHarness(s).run(req)

        print(f"\nstop_reason={t.stop_reason} model={t.model} error={t.error}")
        print(f"turns={len(t.turns)} usage={t.usage}")

        out = Path(d) / "result.txt"
        wrote = out.exists()
        content = out.read_text().strip() if wrote else "<missing>"
        print(f"result.txt exists={wrote} content={content!r}")

        ok = t.ok and wrote and _MARKER in content
        print("\nSMOKE", "PASS" if ok else "FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
