"""Phase 3 acceptance (gate 3.9, the phase gate).

Unlike the Phase 1/2 e2e suites, these five criteria need no live stack (no
kind cluster, no running consumer, no AWS): every Phase 3 gate's real logic
lives in pure, injectable functions (the GE suite, the corridor transforms,
the holdout gate, shadow diff, and the promotion state machine), so there is
nothing here to skip-guard behind an env var - these run in the ordinary
suite, every time. A live AWS-showcase run (real SageMaker canary weights,
a real EMR job) is out of scope for this session (no demo window) and would
be Arun-run, matching every other AWS-only piece of this phase.

The five criteria map to the master plan (PHASE_3.md's acceptance mapping):
  (a) bad data fails the GE suite and the EMR job halts with no Iceberg write
  (b) a holdout-failing candidate never reaches shadow or canary
  (c) a clean candidate passes shadow and ramps through every canary weight
  (d) a regression fixture triggers auto-rollback and restores the champion
  (e) the EMR module's plan-time termination attribute is present
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from e2e.lake_helpers import EMR_MODULE_PATH, emr_module_has_auto_terminate
from lake.backfill.job import DataQualityGateFailure, _gate_and_canonicalize_partition
from mlops.holdout_gate import HoldoutGateResult, run_holdout_gate
from mlops.promote import CANARY_WEIGHTS, run_promotion
from mlops.registry import register_candidate
from mlops.shadow_diff import ShadowDiffResult, score_diff


def test_a_bad_data_fails_the_ge_suite_and_the_job_halts_with_no_write():
    bad_partition = pd.DataFrame(
        [
            {
                "mmsi": 42,
                "t": "2024-06-01T00:00:00Z",
                "lat": 40.0,
                "lon": -74.0,
                "sog": 5.0,
                "cog": 1.0,
            }
        ]
    )  # mmsi 42 is out of the valid MMSI range: the GE suite must reject it
    with pytest.raises(DataQualityGateFailure):
        _gate_and_canonicalize_partition(bad_partition)
    # DataQualityGateFailure propagating IS the halt: lake/backfill/job.py's
    # mapInPandas wrapper never reaches the Iceberg write step below a raise


def test_b_a_failing_holdout_gate_never_reaches_shadow_or_canary():
    rng = np.random.default_rng(99)
    n = 200
    labels = rng.integers(0, 2, size=n)
    scores = rng.normal(0, 1, size=n)  # uninformative: fails the AUC threshold
    gate = run_holdout_gate(
        labels=labels,
        scores=scores,
        predicted_mean=rng.normal(0, 1, size=n),
        predicted_sigma=np.full(n, 1.0),
        observed=rng.normal(0, 1, size=n),
    )
    assert not gate.passed

    class UnreachableSageMaker:
        def create_model_package(self, **kwargs):
            raise AssertionError("register_candidate must refuse before calling SageMaker")

    with pytest.raises(ValueError):
        register_candidate(
            sagemaker_client=UnreachableSageMaker(),
            model_package_group_name="hm-pidpm",
            model_data_url="s3://bucket/model.tar.gz",
            container_image="image:latest",
            holdout_result=gate,
        )

    weights_set: list[int] = []
    promotion = run_promotion(
        holdout_result=gate,
        shadow_result=None,
        burn_check=lambda w: False,
        set_canary_weight=weights_set.append,
        revert_to_champion=lambda: None,
    )
    assert promotion.final_status == "rejected_gate"
    assert weights_set == []


def test_c_a_clean_candidate_passes_shadow_and_ramps_through_every_canary_weight():
    gate = HoldoutGateResult(auc=0.95, crps=0.2, calibration_ratio=1.0, passed=True, failures=[])
    champion = np.full(50, 0.3)
    shadow = champion + 0.01
    shadow_result = score_diff(champion, shadow, max_divergence=0.05)
    assert shadow_result.passed

    weights_set: list[int] = []
    reverted = {"called": False}
    promotion = run_promotion(
        holdout_result=gate,
        shadow_result=shadow_result,
        burn_check=lambda w: False,
        set_canary_weight=weights_set.append,
        revert_to_champion=lambda: reverted.__setitem__("called", True),
    )
    assert promotion.final_status == "promoted"
    assert weights_set == list(CANARY_WEIGHTS)
    assert reverted["called"] is False


def test_d_a_regression_fixture_triggers_auto_rollback_and_restores_the_champion():
    gate = HoldoutGateResult(auc=0.95, crps=0.2, calibration_ratio=1.0, passed=True, failures=[])
    shadow_result = ShadowDiffResult(
        mean_abs_diff=0.01, max_abs_diff=0.02, n_samples=50, passed=True
    )

    weights_set: list[int] = []
    champion_restored = {"called": False}

    def revert_to_champion() -> None:
        champion_restored["called"] = True

    promotion = run_promotion(
        holdout_result=gate,
        shadow_result=shadow_result,
        burn_check=lambda w: w == 25,  # the regression only surfaces at 25% traffic
        set_canary_weight=weights_set.append,
        revert_to_champion=revert_to_champion,
    )
    assert promotion.final_status == "rolled_back"
    assert champion_restored["called"] is True
    assert weights_set == [5, 25]  # never advanced to 50 or 100 after the burn


def test_e_the_emr_modules_plan_time_termination_attribute_is_present():
    assert emr_module_has_auto_terminate(EMR_MODULE_PATH.read_text())
