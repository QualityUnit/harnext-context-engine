"""Harness layer: fake harness edits, runner subprocess, claude harness wiring."""

import os
import subprocess
import sys

from harnext_builder.harness.base import ConversationTranscript, HarnessRequest
from harnext_builder.harness.claude_code import ClaudeCodeHarness
from harnext_builder.harness.registry import get_harness


async def test_fake_harness_makes_real_edits(tmp_path):
    (tmp_path / "INDEX.md").write_text("# Index\n")
    req = HarnessRequest(
        harness="fake",
        working_dir=str(tmp_path),
        instruction="incorporate event X",
        system_prompt="sp",
    )
    t = await get_harness("fake").run(req)
    assert t.stop_reason == "completed"
    assert (tmp_path / "_meta" / "last_build.md").exists()
    assert "incorporated by fake harness" in (tmp_path / "INDEX.md").read_text()


def test_runner_subprocess_computes_files_changed(tmp_path):
    wd = tmp_path / "fs"
    wd.mkdir()
    (wd / "INDEX.md").write_text("# Index\n")
    req = HarnessRequest(
        harness="fake",
        working_dir=str(wd),
        instruction="incorporate event Y",
        system_prompt="sp",
    )
    req_path = tmp_path / "req.json"
    req_path.write_text(req.model_dump_json())
    res_path = tmp_path / "res.json"

    env = {**os.environ, "REQUEST_PATH": str(req_path), "RESULT_PATH": str(res_path)}
    p = subprocess.run(
        [sys.executable, "-m", "harnext_builder.harness.runner"],
        cwd=wd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stderr

    t = ConversationTranscript.model_validate_json(res_path.read_text())
    assert t.stop_reason == "completed"
    assert "A _meta/last_build.md" in t.files_changed
    assert "M INDEX.md" in t.files_changed


def test_claude_harness_constructs():
    h = get_harness("claude_code")
    assert isinstance(h, ClaudeCodeHarness)
    assert h.name == "claude_code"
