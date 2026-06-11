"""Harnext harness — drives the Harnext SDK (``harnext_sdk``) in-process.

Harnext is provider-agnostic: the same agent loop runs on Anthropic, OpenAI,
NVIDIA NIM, Ollama, and more, selected by ``provider`` + ``model``. The SDK
subprocesses the ``harnext`` CLI with a Claude-Agent-SDK-compatible API
(``query`` + ``HarnextAgentOptions`` + the same message/block types), so this
harness is structurally the Claude Code harness with three differences:

  * ``provider``/``model`` are explicit (routed from :class:`BuilderSettings`),
  * the provider API key is injected into the CLI subprocess via ``options.env``
    under the env-var name the provider expects (e.g. ``NVIDIA_API_KEY``),
  * harnext's terminal ``ResultMessage`` carries no ``stop_reason``, so the run
    outcome is read from its ``is_error`` flag (success ⇒ ``completed``).

Requires the ``harnext`` CLI on PATH (``npm i -g harnext``) or ``HARNEXT_CLI_PATH``.
Headless + least-privilege: ``permission_mode=dontAsk`` makes ``allowed_tools`` a
default-deny whitelist (anything else is denied, not prompted).
"""

from __future__ import annotations

import asyncio
import json
from typing import cast

from harnext_sdk import (
    AssistantMessage,
    HarnextAgentOptions,
    PermissionMode,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from harnext_builder.harness.base import (
    ConversationTranscript,
    HarnessRequest,
    TranscriptTurn,
)
from harnext_builder.settings import BuilderSettings

_CLIP = 4000


def _clip(s: str) -> str:
    return s if len(s) <= _CLIP else s[:_CLIP] + "…"


def _blocks_to_turns(content, turns: list[TranscriptTurn]) -> None:
    """Map an Assistant/User message's content (str or list of blocks) to turns."""
    if isinstance(content, str):
        if content.strip():
            turns.append(TranscriptTurn(role="assistant", content=_clip(content)))
        return
    for block in content or []:
        if isinstance(block, TextBlock):
            if block.text.strip():
                turns.append(TranscriptTurn(role="assistant", content=_clip(block.text)))
        elif isinstance(block, ThinkingBlock):
            turns.append(TranscriptTurn(role="thinking", content=_clip(block.thinking)))
        elif isinstance(block, ToolUseBlock):
            turns.append(
                TranscriptTurn(
                    role="tool_use",
                    tool_name=block.name,
                    content=_clip(json.dumps(block.input, default=str)),
                )
            )
        elif isinstance(block, ToolResultBlock):
            turns.append(TranscriptTurn(role="tool_result", content=_clip(str(block.content))))


class HarnextHarness:
    name = "harnext"

    def __init__(self, settings: BuilderSettings | None = None) -> None:
        # Read once; provider/model/key live in env (docker env_file in prod, the
        # inherited process env in the runner subprocess).
        self.s = settings or BuilderSettings()

    async def run(self, req: HarnessRequest) -> ConversationTranscript:
        model = self.s.harnext_model or req.model

        # The provider key is read from any of the aliased env vars and re-exported
        # under the name the chosen provider expects (NVIDIA NIM → NVIDIA_API_KEY).
        env: dict[str, str] = {}
        if self.s.harnext_api_key:
            env[self.s.harnext_api_key_env] = self.s.harnext_api_key

        options = HarnextAgentOptions(
            cwd=req.working_dir,
            provider=self.s.harnext_provider,
            model=model,
            system_prompt=req.system_prompt,
            allowed_tools=req.allowed_tools,
            disallowed_tools=req.disallowed_tools,
            permission_mode=cast(
                PermissionMode, self.s.harnext_permission_mode
            ),  # dontAsk: deny-by-default
            max_turns=req.max_turns,
            setting_sources=["project"],  # auto-load ./CLAUDE.md from the mount
            env=env,
        )

        turns: list[TranscriptTurn] = []
        usage: dict = {}
        stop_reason = "completed"
        error: str | None = None

        try:
            async with asyncio.timeout(req.timeout_s):
                async for msg in query(prompt=req.instruction, options=options):
                    if isinstance(msg, SystemMessage):
                        turns.append(TranscriptTurn(role="system", content=str(msg.subtype)))
                    elif isinstance(msg, AssistantMessage):
                        # Per-turn stop_reason ("tool_use"/"end_turn") is not the run
                        # outcome — that's decided by the terminal ResultMessage.
                        model = msg.model or model
                        _blocks_to_turns(msg.content, turns)
                    elif isinstance(msg, UserMessage):
                        _blocks_to_turns(msg.content, turns)
                    elif isinstance(msg, ResultMessage):
                        usage = {
                            "usage": msg.usage,
                            "total_cost_usd": msg.total_cost_usd,
                            "num_turns": msg.num_turns,
                        }
                        if msg.result:
                            turns.append(TranscriptTurn(role="result", content=_clip(msg.result)))
                        if msg.is_error:
                            # Any errored run (incl. max-turns, via subtype) is not
                            # committable — mark error so the build rolls back.
                            stop_reason = "error"
                            error = msg.result or str(msg.subtype) or "result error"
        except TimeoutError:
            stop_reason = "timeout"
            error = f"harness exceeded {req.timeout_s}s"
        except Exception as e:  # noqa: BLE001 — surface any SDK/CLI failure as a build error
            stop_reason = "error"
            error = f"{type(e).__name__}: {e}"

        return ConversationTranscript(
            harness=self.name,
            model=model,
            turns=turns,
            usage=usage,
            stop_reason=stop_reason,
            error=error,
        )
