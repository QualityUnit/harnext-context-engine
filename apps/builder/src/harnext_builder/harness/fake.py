"""Fake harness — deterministic, no API/CLI.

Simulates incorporation by making real edits to the mounted FS, so the full
builder pipeline (runner → backend → store → ledger) can be tested end to end
without an Anthropic key. Enabled via HARNEXT_HARNESS=fake.
"""

from __future__ import annotations

from pathlib import Path

from harnext_builder.harness.base import (
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

        # Prove the changed files are readable from `_event/`: fold their content
        # into the durable marker. The `_event/` tree itself is reference-only and
        # is removed before snapshotting, so this is the only trace that survives.
        seen = ""
        manifest = wd / "_event" / "MANIFEST.md"
        if manifest.exists():
            files = sorted(p for p in (wd / "_event").rglob("*") if p.is_file())
            seen = "\n\n## _event files seen\n" + "".join(
                f"\n### {p.relative_to(wd)}\n{p.read_text()[:4000]}\n" for p in files
            )

        marker = wd / "_meta" / "last_build.md"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"# Last build\n\n{req.instruction[:4000]}\n{seen}")

        return ConversationTranscript(
            harness=self.name,
            model="fake",
            turns=[TranscriptTurn(role="assistant", content="incorporated (fake harness)")],
            stop_reason="completed",
            usage={},
        )
