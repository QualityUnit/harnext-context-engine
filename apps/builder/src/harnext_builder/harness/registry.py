"""Select a harness implementation by name."""

from __future__ import annotations

from harnext_builder.harness.base import Harness


def get_harness(name: str) -> Harness:
    if name == "claude_code":
        from harnext_builder.harness.claude_code import ClaudeCodeHarness

        return ClaudeCodeHarness()
    if name == "fake":
        from harnext_builder.harness.fake import FakeHarness

        return FakeHarness()
    if name == "harnext":
        from harnext_builder.harness.harnext import HarnextHarness

        return HarnextHarness()
    if name == "codex":
        raise NotImplementedError("codex harness lands after claude_code")
    raise ValueError(f"unknown harness: {name!r}")
