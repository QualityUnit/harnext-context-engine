"""The routing decision: fast = Rules(e) OR anomaly_score(e) > threshold."""

from __future__ import annotations

from dataclasses import dataclass

from harnext_shared import CloudEvent

from harnext_classifier.anomaly import AnomalyScorer
from harnext_classifier.rules import rules_match
from harnext_classifier.settings import ClassifierSettings


@dataclass
class Decision:
    lane: str  # fast | batch
    reason: str  # rule id | "anomaly" | "baseline"
    score: float


class Router:
    def __init__(self, scorer: AnomalyScorer, settings: ClassifierSettings) -> None:
        self.scorer = scorer
        self.threshold = settings.anomaly_threshold

    async def decide(self, event: CloudEvent) -> Decision:
        rule = rules_match(event)
        score = await self.scorer.score(event)  # always update the baseline
        if rule is not None:
            return Decision("fast", rule, score)
        if score > self.threshold:
            return Decision("fast", "anomaly", score)
        return Decision("batch", "baseline", score)
