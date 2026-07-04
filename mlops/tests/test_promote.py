from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from mlops.holdout_gate import HoldoutGateResult
from mlops.promote import CANARY_WEIGHTS, PromotionResult, run_promotion
from mlops.shadow_diff import ShadowDiffResult

EXPECTATIONS = Path(__file__).parent.parent / "fixtures" / "expectations.json"

PASSING_GATE = HoldoutGateResult(
    auc=0.95, crps=0.2, calibration_ratio=1.0, passed=True, failures=[]
)
FAILING_GATE = HoldoutGateResult(
    auc=0.5, crps=0.2, calibration_ratio=1.0, passed=False, failures=["auc too low"]
)
CLEAN_SHADOW = ShadowDiffResult(mean_abs_diff=0.01, max_abs_diff=0.02, n_samples=100, passed=True)
DIRTY_SHADOW = ShadowDiffResult(mean_abs_diff=0.5, max_abs_diff=0.9, n_samples=100, passed=False)


class _Recorder:
    def __init__(self) -> None:
        self.weights_set: list[int] = []
        self.reverted = False

    def set_canary_weight(self, weight: int) -> None:
        self.weights_set.append(weight)

    def revert_to_champion(self) -> None:
        self.reverted = True


def test_a_failing_holdout_gate_never_reaches_shadow_or_canary():
    rec = _Recorder()
    result = run_promotion(
        holdout_result=FAILING_GATE,
        shadow_result=None,
        burn_check=lambda w: False,
        set_canary_weight=rec.set_canary_weight,
        revert_to_champion=rec.revert_to_champion,
    )
    assert result.final_status == "rejected_gate"
    assert [s.stage for s in result.steps] == ["gate"]
    assert rec.weights_set == []
    assert rec.reverted is False


def test_missing_shadow_result_never_reaches_canary():
    rec = _Recorder()
    result = run_promotion(
        holdout_result=PASSING_GATE,
        shadow_result=None,
        burn_check=lambda w: False,
        set_canary_weight=rec.set_canary_weight,
        revert_to_champion=rec.revert_to_champion,
    )
    assert result.final_status == "rejected_shadow"
    assert rec.weights_set == []


def test_a_dirty_shadow_diff_never_reaches_canary():
    rec = _Recorder()
    result = run_promotion(
        holdout_result=PASSING_GATE,
        shadow_result=DIRTY_SHADOW,
        burn_check=lambda w: False,
        set_canary_weight=rec.set_canary_weight,
        revert_to_champion=rec.revert_to_champion,
    )
    assert result.final_status == "rejected_shadow"
    assert rec.weights_set == []


def test_a_clean_candidate_ramps_through_every_canary_weight():
    rec = _Recorder()
    result = run_promotion(
        holdout_result=PASSING_GATE,
        shadow_result=CLEAN_SHADOW,
        burn_check=lambda w: False,  # never burning
        set_canary_weight=rec.set_canary_weight,
        revert_to_champion=rec.revert_to_champion,
    )
    assert result.final_status == "promoted"
    assert rec.weights_set == list(CANARY_WEIGHTS)
    assert rec.reverted is False


@pytest.mark.parametrize("burn_at_weight", CANARY_WEIGHTS)
def test_a_burn_at_any_weight_triggers_an_immediate_full_revert(burn_at_weight):
    rec = _Recorder()
    result = run_promotion(
        holdout_result=PASSING_GATE,
        shadow_result=CLEAN_SHADOW,
        burn_check=lambda w: w == burn_at_weight,
        set_canary_weight=rec.set_canary_weight,
        revert_to_champion=rec.revert_to_champion,
    )
    assert result.final_status == "rolled_back"
    assert rec.reverted is True
    # weight only ever set up to and including the burning step, never beyond
    expected_weights = [w for w in CANARY_WEIGHTS if w <= burn_at_weight]
    assert rec.weights_set == expected_weights
    assert result.steps[-1].stage == f"canary_{burn_at_weight}"
    assert result.steps[-1].action == "revert"


def test_promotion_result_transition_sequence_matches_the_pinned_clean_run():
    result = run_promotion(
        holdout_result=PASSING_GATE,
        shadow_result=CLEAN_SHADOW,
        burn_check=lambda w: False,
        set_canary_weight=lambda w: None,
        revert_to_champion=lambda: None,
    )
    pinned = json.loads(EXPECTATIONS.read_text())["promotion_state_machine"]["clean_run"]
    live = [asdict(s) for s in result.steps]
    assert live == pinned, (
        "the clean-run transition sequence changed; if intentional, update "
        "mlops/fixtures/expectations.json AND docs/phases/PHASE_3.md in the same commit"
    )
    assert result.final_status == "promoted"


def test_promotion_result_transition_sequence_matches_the_pinned_rollback_run():
    result = run_promotion(
        holdout_result=PASSING_GATE,
        shadow_result=CLEAN_SHADOW,
        burn_check=lambda w: w == 25,  # burns at the second canary step
        set_canary_weight=lambda w: None,
        revert_to_champion=lambda: None,
    )
    pinned = json.loads(EXPECTATIONS.read_text())["promotion_state_machine"][
        "rollback_run_burns_at_25"
    ]
    live = [asdict(s) for s in result.steps]
    assert live == pinned, (
        "the rollback-run transition sequence changed; if intentional, update "
        "mlops/fixtures/expectations.json AND docs/phases/PHASE_3.md in the same commit"
    )
    assert result.final_status == "rolled_back"


def test_promotion_result_defaults_are_sane():
    empty = PromotionResult()
    assert empty.steps == []
    assert empty.final_status == "rejected_gate"
