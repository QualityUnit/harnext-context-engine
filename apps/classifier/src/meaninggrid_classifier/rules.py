"""Rules floor — deterministic FAST triggers for urgent-but-not-anomalous events.

A small, source-aware rule set (proposal §Event classification step 2). Returns
the matched rule id, or None. The scorer is never consulted when a rule fires.
"""

from __future__ import annotations

from meaninggrid_shared import CloudEvent

_URGENT_LABELS = {"p0", "p1", "security", "critical", "urgent", "incident", "sev1", "sev0"}
_URGENT_WORDS = ("outage", "down", "incident", "urgent", "broken", "regression", "data loss")
_SLACK_MENTIONS = ("<!here>", "<!channel>", "@here", "@channel", "@oncall", "<!subteam")


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

    if event.type == "com.slack.message":
        text = str(data.get("text", "")).lower()
        if any(m in text for m in _SLACK_MENTIONS):
            return "rule:slack-mention"
        if any(w in text for w in _URGENT_WORDS):
            return "rule:slack-urgent-word"

    return None
