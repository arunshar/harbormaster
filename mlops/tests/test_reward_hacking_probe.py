"""Gate 4.5: mlops/reward_hacking_probe.py."""

from __future__ import annotations

from mlops.preference_builder import RewardBreakdown
from mlops.reward_hacking_probe import run_reward_hacking_probe


def _rewards(total: float, hard: float, n: int) -> list[RewardBreakdown]:
    return [RewardBreakdown(total=total, hard=hard, soft=0.0, data=0.0, pref=0.0) for _ in range(n)]


def test_reward_up_and_violations_up_is_blocked():
    baseline = _rewards(total=5.0, hard=0.5, n=10)
    candidate = _rewards(total=8.0, hard=-1.0, n=10)  # higher reward, negative (violating) hard
    result = run_reward_hacking_probe(baseline, candidate)
    assert result.blocked is True
    assert result.reason is not None


def test_reward_up_with_violations_flat_passes():
    baseline = _rewards(total=5.0, hard=0.5, n=10)
    candidate = _rewards(total=8.0, hard=0.5, n=10)
    result = run_reward_hacking_probe(baseline, candidate)
    assert result.blocked is False


def test_reward_up_with_violations_down_passes():
    baseline = _rewards(total=5.0, hard=-0.5, n=10)
    candidate = _rewards(total=8.0, hard=0.5, n=10)
    result = run_reward_hacking_probe(baseline, candidate)
    assert result.blocked is False


def test_reward_down_passes_regardless_of_violations():
    baseline = _rewards(total=8.0, hard=0.5, n=10)
    candidate = _rewards(total=5.0, hard=-1.0, n=10)  # worse reward AND more violations
    result = run_reward_hacking_probe(baseline, candidate)
    assert result.blocked is False


def test_empty_streams_do_not_crash_and_never_block():
    result = run_reward_hacking_probe([], [])
    assert result.blocked is False
    assert result.baseline_mean_reward == 0.0
    assert result.candidate_mean_reward == 0.0


def test_custom_hard_violation_threshold_is_respected():
    baseline = _rewards(total=5.0, hard=0.05, n=10)
    candidate = _rewards(total=8.0, hard=0.02, n=10)
    # with threshold 0.0 neither counts as a violation -> passes
    assert (
        run_reward_hacking_probe(baseline, candidate, hard_violation_threshold=0.0).blocked is False
    )
    # with threshold 0.1 both count as violations at the same rate -> still passes (not "up")
    assert (
        run_reward_hacking_probe(baseline, candidate, hard_violation_threshold=0.1).blocked is False
    )
