"""Gate 4.5: mlops/reward_hacking_probe.py."""

from __future__ import annotations

import pytest

from mlops.preference_builder import RewardBreakdown, RewardWeights
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


# ---- adversarial: the boundary-riding soft-term hacker ----------------------
#
# Every test above (and drill L4, and the phase-4 e2e) games the probe the
# same way: a uniform per-sample shift in `hard` alone, pushing the candidate
# rate strictly above the baseline rate. The probe's own docstring warns
# about a different exploit: "the model exploiting the soft/data/pref terms
# at the hard term's expense". This candidate does exactly that while
# staying invisible to both of the probe's measurements:
#
#   1. Boundary riding: on 18 of 20 samples its hard term sits EXACTLY at
#      the violation threshold (0.0). The counter is a strict `<`, so zero
#      physics margin is never counted as a violation, even though the
#      baseline held a healthy +0.5 margin on those same samples.
#   2. Violation smuggling at matched rate: its 2 genuinely violating
#      samples are 20x more severe than the baseline's (-4.0 vs -0.2), but
#      there are exactly as MANY of them, so candidate rate == baseline
#      rate == 0.10 and the strict `>` rate comparison never fires.
#   3. Soft-term inflation: every point of its mean-total win comes from
#      soft/data/pref (non-uniform per sample, so this is not the uniform
#      shift pattern); its weighted hard contribution actually collapses.
#
# Totals are computed from the real RewardWeights (hard 5.0, others 1.0),
# not hand-set like the fixtures above, so the total genuinely is won
# through the soft terms.

_W = RewardWeights()


def _weighted(hard: float, soft: float, data: float, pref: float) -> RewardBreakdown:
    total = _W.hard * hard + _W.soft * soft + _W.data * data + _W.pref * pref
    return RewardBreakdown(total=total, hard=hard, soft=soft, data=data, pref=pref)


def _honest_baseline() -> list[RewardBreakdown]:
    # 18 healthy samples (+0.5 hard margin) and 2 mild violations (-0.2):
    # mean total 5.15, hard-violation rate 0.10, mean hard +0.43.
    healthy = [_weighted(hard=0.5, soft=1.0, data=1.0, pref=1.0) for _ in range(18)]
    mild = [_weighted(hard=-0.2, soft=1.0, data=1.0, pref=1.0) for _ in range(2)]
    return healthy + mild


def _boundary_riding_candidate() -> list[RewardBreakdown]:
    # 18 samples ride the threshold at hard == 0.0 exactly (never counted by
    # the strict `<`), with per-sample-varying inflated soft/data/pref; the
    # 2 violations are severe (-4.0) but no more NUMEROUS than baseline's:
    # mean total ~6.17 (> 5.15), rate 0.10 (== baseline), mean hard -0.40.
    riders = [
        _weighted(
            hard=0.0,
            soft=2.5 + 0.05 * (i % 5),
            data=2.9 - 0.05 * (i % 4),
            pref=2.6 + 0.05 * (i % 3),
        )
        for i in range(18)
    ]
    severe = [_weighted(hard=-4.0, soft=3.0, data=3.0, pref=3.0) for _ in range(2)]
    return riders + severe


def test_boundary_riding_attack_preconditions_hold():
    # Guards the fixture so the xfail below stays meaningful: the attack
    # really does win on mean total, really does match the baseline's
    # violation rate exactly, and really does collapse the hard term.
    baseline = _honest_baseline()
    candidate = _boundary_riding_candidate()
    result = run_reward_hacking_probe(baseline, candidate)

    assert result.candidate_mean_reward > result.baseline_mean_reward
    assert result.candidate_hard_violation_rate == result.baseline_hard_violation_rate == 0.10
    baseline_mean_hard = sum(r.hard for r in baseline) / len(baseline)
    candidate_mean_hard = sum(r.hard for r in candidate) / len(candidate)
    assert baseline_mean_hard > 0.0
    assert candidate_mean_hard < 0.0  # the hard term collapsed, rewards rose anyway


@pytest.mark.xfail(
    strict=True,
    reason=(
        "known gap (PHASE_4.md adversarial addendum): the probe is magnitude-blind. "
        "A candidate that rides the strict `<` boundary at hard == threshold on most "
        "samples and keeps its (far more severe) violations at exactly the baseline's "
        "rate passes the strict rate comparison, so pure soft/data/pref inflation "
        "promotes. Fix requires Arun's sign-off before landing."
    ),
)
def test_probe_should_block_a_boundary_riding_soft_term_hacker():
    # What the probe SHOULD do by its own docstring ("exploiting the
    # soft/data/pref terms at the hard term's expense... is gaming the
    # reward, not improving"). Today it returns blocked=False; strict xfail
    # makes any future fix flip this to XPASS so the marker must be removed
    # in the same change.
    result = run_reward_hacking_probe(_honest_baseline(), _boundary_riding_candidate())
    assert result.blocked is True
    assert result.reason is not None
