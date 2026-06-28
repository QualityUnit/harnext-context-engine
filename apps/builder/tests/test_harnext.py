"""Harnext harness: registry wiring, option routing (provider/model/key/cwd/tools),
and the SDK-message → ConversationTranscript mapping. Mocks ``harnext_sdk.query``
so nothing hits the CLI or a provider."""

from __future__ import annotations

import harnext_builder.harness.harnext as harnext_mod
from harnext_builder.harness.base import HarnessRequest
from harnext_builder.harness.harnext import HarnextHarness
from harnext_builder.harness.registry import get_harness
from harnext_builder.settings import BuilderSettings
from harnext_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)


def _settings(**over) -> BuilderSettings:
    base = dict(
        harnext_provider="nvidia",
        harnext_model="deepseek-ai/deepseek-v4-flash",
        harnext_api_key="nvapi-test",
        harnext_api_key_env="NVIDIA_API_KEY",
        harnext_permission_mode="dontAsk",
    )
    base.update(over)
    return BuilderSettings(**base)


def _req(**over) -> HarnessRequest:
    base = dict(
        harness="harnext",
        working_dir="/tmp/org-fs",
        instruction="Incorporate the event",
        system_prompt="You are the builder.",
        model="claude-sonnet-4-6",  # should be overridden by harnext_model
        max_turns=7,
        timeout_s=120,
    )
    base.update(over)
    return HarnessRequest(**base)


def _patch_query(monkeypatch, messages, capture: dict):
    """Replace harnext_sdk.query with a stub that records the options it was given
    and replays ``messages`` as an async stream."""

    async def fake_query(*, prompt, options=None):
        capture["prompt"] = prompt
        capture["options"] = options
        for m in messages:
            yield m

    # The harness binds `query` at import, so patch it in the harness module.
    monkeypatch.setattr(harnext_mod, "query", fake_query)


def test_registry_resolves_harnext():
    assert isinstance(get_harness("harnext"), HarnextHarness)


async def test_options_routing(monkeypatch):
    cap: dict = {}
    _patch_query(
        monkeypatch,
        [ResultMessage("success", False, "done", "s1", 2, 100, 0.0, {"input_tokens": 1})],
        cap,
    )
    h = HarnextHarness(_settings())
    await h.run(_req())

    o = cap["options"]
    assert cap["prompt"] == "Incorporate the event"
    assert o.provider == "nvidia"
    assert o.model == "deepseek-ai/deepseek-v4-flash"  # harnext_model wins over req.model
    assert o.cwd == "/tmp/org-fs"
    assert o.permission_mode == "dontAsk"
    assert o.max_turns == 7
    assert o.system_prompt == "You are the builder."
    assert "Read" in o.allowed_tools and "Bash" in o.allowed_tools
    assert "WebSearch" in o.disallowed_tools
    # the provider key is injected under the env-var name the provider reads
    assert o.env.get("NVIDIA_API_KEY") == "nvapi-test"


async def test_openrouter_routing(monkeypatch):
    """OpenRouter (harnext 1.5): provider=openrouter, key read from the
    OPENROUTER_API_KEY alias and re-exported under OPENROUTER_API_KEY for the CLI."""
    cap: dict = {}
    _patch_query(
        monkeypatch,
        [ResultMessage("success", False, "done", "s1", 2, 100, 0.0, {"input_tokens": 1})],
        cap,
    )
    s = _settings(
        harnext_provider="openrouter",
        harnext_model="anthropic/claude-sonnet-4.5",
        harnext_api_key="sk-or-test",
        harnext_api_key_env="OPENROUTER_API_KEY",
    )
    await HarnextHarness(s).run(_req())

    o = cap["options"]
    assert o.provider == "openrouter"
    assert o.model == "anthropic/claude-sonnet-4.5"
    assert o.env.get("OPENROUTER_API_KEY") == "sk-or-test"


async def test_transcript_maps_messages(monkeypatch):
    cap: dict = {}
    messages = [
        SystemMessage("init", {}),
        AssistantMessage(
            content=[
                ThinkingBlock("let me look"),
                TextBlock("Updating the file."),
                ToolUseBlock("t1", "Edit", {"path": "OVERVIEW.md"}),
            ],
            model="deepseek-ai/deepseek-v4-flash",
            stop_reason="tool_use",
        ),
        UserMessage(content=[ToolResultBlock("t1", "ok", False)]),
        ResultMessage(
            "success",
            False,
            "All done.",
            "s1",
            3,
            4200,
            0.012,
            {"input_tokens": 10, "output_tokens": 5},
        ),
    ]
    _patch_query(monkeypatch, messages, cap)

    t = await HarnextHarness(_settings()).run(_req())
    assert t.harness == "harnext"
    assert t.model == "deepseek-ai/deepseek-v4-flash"
    assert t.stop_reason == "completed" and t.ok and t.error is None
    roles = [(turn.role, turn.tool_name) for turn in t.turns]
    assert ("system", None) in roles
    assert ("thinking", None) in roles
    assert ("assistant", None) in roles
    assert ("tool_use", "Edit") in roles
    assert ("tool_result", None) in roles
    assert ("result", None) in roles
    assert t.usage["num_turns"] == 3
    assert t.usage["usage"]["output_tokens"] == 5


async def test_result_error_rolls_back(monkeypatch):
    cap: dict = {}
    _patch_query(
        monkeypatch,
        [ResultMessage("error_max_turns", True, "ran out of turns", "s1", 7, 9000, 0.0, {})],
        cap,
    )
    t = await HarnextHarness(_settings()).run(_req())
    # is_error → "error" so the build rolls back (ConversationTranscript.ok is False)
    assert t.stop_reason == "error" and not t.ok
    assert "turns" in (t.error or "")


async def test_sdk_exception_becomes_build_error(monkeypatch):
    def boom(*, prompt, options=None):
        raise RuntimeError("CLI not found")

    monkeypatch.setattr(harnext_mod, "query", boom)
    t = await HarnextHarness(_settings()).run(_req())
    assert t.stop_reason == "error" and not t.ok
    assert "CLI not found" in (t.error or "")
