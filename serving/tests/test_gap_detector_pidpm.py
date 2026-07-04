"""GapDetectorAgent's injected pi_dpm_scorer (Phase 3, gate 3.6): a real
score overrides the analytic P_data estimate; a scorer returning None (or no
scorer at all, the Phase 1/2 default) falls back to the existing analytic
estimate untouched. No SageMaker, no AWS: the scorer is a plain injected
async callable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.gap_detector import GapDetectorAgent
from app.config import Settings
from app.models import Anchor

T0 = datetime(2024, 6, 1, tzinfo=UTC)


def _gappy_trajectory() -> list[Anchor]:
    # a 20-minute silence (> the 600s coverage_threshold_s default) over a
    # physically reachable distance at 25 kts
    return [
        Anchor(lat=40.30, lon=-74.15, t=T0),
        Anchor(lat=40.32, lon=-74.14, t=T0 + timedelta(minutes=20)),
    ]


@pytest.mark.asyncio
async def test_no_scorer_uses_the_analytic_estimate_phase1_default():
    agent = GapDetectorAgent(Settings())
    gaps = await agent.detect({"trajectory": _gappy_trajectory()})
    assert len(gaps) == 1
    analytic = gaps[0].p_data
    assert 0.0 <= analytic <= 1.0


@pytest.mark.asyncio
async def test_a_real_scorer_result_overrides_the_analytic_estimate():
    async def fake_scorer(prism):
        return 0.99

    agent = GapDetectorAgent(Settings(), pi_dpm_scorer=fake_scorer)
    gaps = await agent.detect({"trajectory": _gappy_trajectory()})
    assert len(gaps) == 1
    assert gaps[0].p_data == 0.99


@pytest.mark.asyncio
async def test_a_scorer_returning_none_falls_back_to_the_analytic_estimate():
    calls = []

    async def failing_scorer(prism):
        calls.append(prism)
        return None  # disabled/timed-out/failed: PiDpmClient's contract

    agent_with_none = GapDetectorAgent(Settings(), pi_dpm_scorer=failing_scorer)
    agent_without_scorer = GapDetectorAgent(Settings())

    gaps_a = await agent_with_none.detect({"trajectory": _gappy_trajectory()})
    gaps_b = await agent_without_scorer.detect({"trajectory": _gappy_trajectory()})

    assert len(calls) == 1  # the scorer was actually invoked
    assert gaps_a[0].p_data == gaps_b[0].p_data  # identical to the no-scorer path
    assert gaps_a[0].abnormal_gap_measure == gaps_b[0].abnormal_gap_measure
