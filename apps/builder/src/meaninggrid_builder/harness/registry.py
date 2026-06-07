"""Select a harness implementation by name."""

from __future__ import annotations

from meaninggrid_builder.harness.base import Harness


def get_harness(name: str) -> Harness:
    if name == "claude_code":
        from meaninggrid_builder.harness.claude_code import ClaudeCodeHarness

        return ClaudeCodeHarness()
    if name == "fake":
        from meaninggrid_builder.harness.fake import FakeHarness

        return FakeHarness()
    if name == "codex":
        raise NotImplementedError("codex harness lands after claude_code")
    raise ValueError(f"unknown harness: {name!r}")
