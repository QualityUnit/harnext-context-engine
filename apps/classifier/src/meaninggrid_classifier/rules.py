"""Rules floor — deterministic FAST triggers, ahead of the anomaly scorer.

No rules are configured yet, so this is a no-op: ``rules_match`` returns ``None``
for every event and routing falls entirely to the anomaly scorer / windowing.
Per-project rules will become a dashboard-configurable feature (proposal §Event
classification step 2); the router already consults this function, so enabling
rules later is purely additive here.
"""

from __future__ import annotations

from meaninggrid_shared import CloudEvent


def rules_match(event: CloudEvent) -> str | None:
    """Return the matched rule id, or ``None``. No rules are configured yet, so
    this always returns ``None`` (rules become dashboard-configurable later)."""
    return None
