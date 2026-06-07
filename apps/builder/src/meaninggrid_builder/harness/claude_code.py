"""Claude Code harness — drives the Claude Agent SDK in-process.

Requires ``ANTHROPIC_API_KEY`` and the Claude Code CLI on PATH (the SDK shells
out to it). Runs headless: ``permission_mode=bypassPermissions`` so edits never
block, with a filesystem-only tool whitelist + network blocklist so the agent
can only edit the mounted context FS.
"""

from __future__ import annotations

import asyncio
import json

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from meaninggrid_builder.harness.base import (
    ConversationTranscript,
    HarnessRequest,
    TranscriptTurn,
)

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


class ClaudeCodeHarness:
    name = "claude_code"

    async def run(self, req: HarnessRequest) -> ConversationTranscript:
        options = ClaudeAgentOptions(
            cwd=req.working_dir,
            system_prompt=req.system_prompt,
            allowed_tools=req.allowed_tools,
            disallowed_tools=req.disallowed_tools,
            permission_mode="bypassPermissions",
            max_turns=req.max_turns,
            model=req.model,
            setting_sources=["project"],  # auto-load ./CLAUDE.md from the mount
        )

        turns: list[TranscriptTurn] = []
        usage: dict = {}
        model = req.model
        stop_reason = "completed"
        error: str | None = None

        try:
            async with asyncio.timeout(req.timeout_s):
                async for msg in query(prompt=req.instruction, options=options):
                    if isinstance(msg, SystemMessage):
                        turns.append(TranscriptTurn(role="system", content=str(msg.subtype)))
                    elif isinstance(msg, AssistantMessage):
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
                            stop_reason = "error"
                            error = msg.result or str(msg.errors) or "result error"
                        elif msg.stop_reason:
                            stop_reason = msg.stop_reason
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
