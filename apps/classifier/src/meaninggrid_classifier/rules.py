"""Rules floor — deterministic FAST triggers for urgent-but-not-anomalous events.

A small, source-aware rule set (proposal §Event classification step 2). Returns
the matched rule id, or None. The scorer is never consulted when a rule fires.
"""

from __future__ import annotations

from meaninggrid_shared import CloudEvent

_URGENT_LABELS = {"p0", "p1", "security", "critical", "urgent", "incident", "sev1", "sev0"}
_URGENT_WORDS = ("outage", "down", "incident", "urgent", "broken", "regression", "data loss")
# Broadcast/at-mentions across chat providers — Slack (``<!here>``, ``<!subteam``)
# and Discord (``@everyone``, role mentions ``<@&id>``).
_CHAT_MENTIONS = (
    "<!here>",
    "<!channel>",
    "@here",
    "@channel",
    "@everyone",
    "@oncall",
    "<!subteam",
    "<@&",
)
# Chat message event types → the provider tag used in the matched rule id.
_CHAT_TYPES = {"com.slack.message": "slack", "com.discord.message": "discord"}


def rules_match(event: CloudEvent) -> str | None:
    data = event.data or {}

    # explicit urgency field (any source)
    if str(data.get("urgency", "")).upper() in {"P0", "P1"}:
        return "rule:urgency-field"

    if event.type in ("com.github.issue", "com.github.pull_request"):
        labels = {str(label).lower() for label in data.get("labels", [])}
        if labels & _URGENT_LABELS:
            return "rule:github-urgent-label"
        title = str(data.get("title", "")).lower()
        if any(w in title for w in _URGENT_WORDS):
            return "rule:github-urgent-title"

    provider = _CHAT_TYPES.get(event.type)
    if provider:  # slack / discord chat messages
        text = str(data.get("text", "")).lower()
        if any(m in text for m in _CHAT_MENTIONS):
            return f"rule:{provider}-mention"
        if any(w in text for w in _URGENT_WORDS):
            return f"rule:{provider}-urgent-word"

    return None
