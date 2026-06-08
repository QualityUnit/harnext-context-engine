"""The harness abstraction.

A Harness runs a coding agent over a working directory (the mounted org context
FS) to incorporate events, and returns a uniform ``ConversationTranscript``.
Both Claude Code (Claude Agent SDK, in-process) and Codex (``codex exec``) can
implement it. The harness only touches files under ``working_dir`` — it knows
nothing about Kafka, the org DB, or snapshots — which is what keeps builder
agents stateless. ``files_changed`` is recomputed from the FS by the runner, not
trusted from the model, so persistence is decoupled from which agent ran.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# The builder agent's tool policy. permission_mode=dontAsk makes ALLOWED_TOOLS a
# default-deny whitelist (anything not listed is denied, not prompted), and
# DENIED_TOOLS is belt-and-suspenders on top. Bash is allowed but OS-sandboxed
# (see claude_code.py): its writes are confined to working_dir and its network
# egress is denied — deliberate network goes through WebFetch instead. WebSearch
# (open-ended web) and Task (subagent spawning) stay denied to keep the agent
# single-process and auditable.
ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "LS", "TodoWrite",
    "Bash",
]
DENIED_TOOLS = ["WebFetch", "WebSearch", "Task"]


class HarnessRequest(BaseModel):
    harness: str
    working_dir: str
    instruction: str
    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=lambda: list(ALLOWED_TOOLS))
    disallowed_tools: list[str] = Field(default_factory=lambda: list(DENIED_TOOLS))
    model: str | None = None
    max_turns: int = 40
    timeout_s: int = 300


class TranscriptTurn(BaseModel):
    role: str  # system | assistant | thinking | tool_use | tool_result | result
    content: str = ""
    tool_name: str | None = None


class ConversationTranscript(BaseModel):
    harness: str
    model: str | None = None
    turns: list[TranscriptTurn] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)  # "A/M/D <relpath>"
    usage: dict[str, Any] = Field(default_factory=dict)
    stop_reason: str = "completed"  # completed | error | max_turns | timeout
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.stop_reason not in ("error",)


@runtime_checkable
class Harness(Protocol):
    name: str

    async def run(self, req: HarnessRequest) -> ConversationTranscript: ...
