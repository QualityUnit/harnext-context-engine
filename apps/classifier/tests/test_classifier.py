"""Classifier: rules floor, per-entity anomaly burst, windowing, routing."""

from datetime import UTC, datetime, timedelta

from meaninggrid_classifier.anomaly import AnomalyScorer
from meaninggrid_classifier.router import Router
from meaninggrid_classifier.rules import rules_match
from meaninggrid_classifier.settings import ClassifierSettings
from meaninggrid_classifier.windows import WindowManager
from meaninggrid_shared import CloudEvent, init_db, make_engine, make_sessionmaker

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _ev(
    eid,
    *,
    type="com.github.commit",
    subject="repo:acme/web",
    data=None,
    t=_BASE,
    source="github:acme/web",
):
    return CloudEvent(
        id=eid, source=source, type=type, subject=subject, time=t, mgtenant="acme", data=data or {}
    )


def test_rules_floor():
    assert rules_match(_ev("1", type="com.github.issue", data={"labels": ["P0"], "title": "x"}))
    assert rules_match(
        _ev("2", type="com.slack.message", source="slack:C1", data={"text": "<!here> help"})
    )
    assert rules_match(_ev("3", data={"urgency": "P0"}))
    assert rules_match(
        _ev("4", type="com.github.issue", data={"title": "prod outage now", "labels": []})
    )
    assert rules_match(_ev("5", type="com.github.commit", data={"message": "routine"})) is None


async def _scorer(tmp_path, min_samples=3):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/m.sqlite")
    await init_db(engine)
    settings = ClassifierSettings(anomaly_min_samples=min_samples, anomaly_threshold=3.0)
    return AnomalyScorer(make_sessionmaker(engine), settings), engine, settings


async def test_anomaly_detects_burst(tmp_path):
    scorer, engine, _ = await _scorer(tmp_path)
    try:
        t = _BASE
        scores = [await scorer.score(_ev("e0", t=t))]
        for i, gap in enumerate([90, 110, 90, 110, 90, 110]):  # baseline ~100±10
            t = t + timedelta(seconds=gap)
            scores.append(await scorer.score(_ev(f"e{i + 1}", t=t)))
        # a sudden burst: gap of 1s where the entity normally waits ~100s
        t = t + timedelta(seconds=1)
        burst = await scorer.score(_ev("burst", t=t))

        assert burst > 3.0  # well above threshold
        assert max(scores[3:]) < 3.0  # warmed-up baseline stays calm
    finally:
        await engine.dispose()


async def test_window_closes_on_max_events():
    units = []
    wm = WindowManager(
        gap_s=1000, max_events=3, max_age_s=1000, emit=lambda cu: _collect(units, cu)
    )
    for i in range(3):
        await wm.add(_ev(f"e{i}", t=_BASE + timedelta(seconds=i)))
    assert len(units) == 1 and len(units[0].events) == 3
    assert units[0].subject == "repo:acme/web"


async def test_window_closes_on_gap_and_flush():
    units = []
    wm = WindowManager(
        gap_s=0.0, max_events=100, max_age_s=1000, emit=lambda cu: _collect(units, cu)
    )
    await wm.add(_ev("e0"))
    await wm.sweep()  # gap_s=0 → immediately due
    assert len(units) == 1

    units.clear()
    wm2 = WindowManager(
        gap_s=1000, max_events=100, max_age_s=1000, emit=lambda cu: _collect(units, cu)
    )
    await wm2.add(_ev("x"))
    await wm2.flush_all()
    assert len(units) == 1


async def test_router(tmp_path):
    scorer, engine, settings = await _scorer(tmp_path)
    try:
        router = Router(scorer, settings)
        # rule → fast
        d1 = await router.decide(_ev("i", type="com.github.issue", data={"labels": ["security"]}))
        assert d1.lane == "fast" and d1.reason.startswith("rule:")
        # normal, no baseline → batch
        d2 = await router.decide(_ev("n", subject="repo:other", data={}))
        assert d2.lane == "batch"
    finally:
        await engine.dispose()


async def _collect(units, cu):
    units.append(cu)
