"""Fake harness — deterministic, no API/CLI.

Simulates incorporation by making real edits to the mounted FS, so the full
builder pipeline (runner → backend → store → ledger) can be tested end to end
without an Anthropic key. Enabled via MEANINGGRID_HARNESS=fake.
"""

from __future__ import annotations

from pathlib import Path

from meaninggrid_builder.harness.base import (
    ConversationTranscript,
    HarnessRequest,
    TranscriptTurn,
)


class FakeHarness:
    name = "fake"

    async def run(self, req: HarnessRequest) -> ConversationTranscript:
        wd = Path(req.working_dir)

        # Append a marker to the index and record the instruction — enough for
        # tests to assert that files changed and the build path is wired.
        index = wd / "INDEX.md"
        with index.open("a") as f:
            f.write("\n<!-- incorporated by fake harness -->\n")

        marker = wd / "_meta" / "last_build.md"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"# Last build\n\n{req.instruction[:4000]}\n")

        return ConversationTranscript(
            harness=self.name,
            model="fake",
            turns=[TranscriptTurn(role="assistant", content="incorporated (fake harness)")],
            stop_reason="completed",
            usage={},
        )
