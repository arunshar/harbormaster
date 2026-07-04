"""The promotion state machine (Phase 3, gate 3.7): holdout gate -> shadow ->
weighted canary 5/25/50/100, with burn-rate-triggered auto-rollback.

Concretizes DR-3's promotion saga (docs/SYSTEM_DESIGN_DECISIONS.md) using
SageMaker's own native production-variant weighting, not Argo CD/Kubernetes
(see docs/phases/PHASE_3.md's decisions-locked note: only the SageMaker
Pi-DPM endpoint is promoted here, the ECS front door does not change on a
model promotion). Every I/O boundary (setting a canary weight, checking the
SLO burn-rate, reverting to the prior champion) is an injected callable, so
the state machine itself is fully unit-testable with zero AWS.

Invariant 3 (docs/phases/PHASE_3.md): canary weight only ever increases
while the burn-rate stays healthy; a breach at any step reverts the FULL
weight to the prior champion in one action, never a partial rollback.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from mlops.holdout_gate import HoldoutGateResult
from mlops.shadow_diff import ShadowDiffResult

CANARY_WEIGHTS: tuple[int, ...] = (5, 25, 50, 100)


@dataclass(frozen=True)
class PromotionStep:
    stage: str
    action: str  # "pass" | "fail" | "advance" | "revert"


@dataclass(frozen=True)
class PromotionResult:
    steps: list[PromotionStep] = field(default_factory=list)
    final_status: str = "rejected_gate"  # | "rejected_shadow" | "rolled_back" | "promoted"


def run_promotion(
    *,
    holdout_result: HoldoutGateResult,
    shadow_result: ShadowDiffResult | None,
    burn_check: Callable[[int], bool],
    set_canary_weight: Callable[[int], None],
    revert_to_champion: Callable[[], None],
) -> PromotionResult:
    """burn_check(weight) -> True means the SLO error budget is burning at
    that canary weight (serving/app/slo.py's machinery, DR-13); False means
    healthy. A candidate that fails the holdout gate never reaches shadow or
    canary at all (invariant 1); the same holds for a failed/missing shadow
    result (a candidate cannot skip shadow to reach canary)."""
    steps: list[PromotionStep] = [
        PromotionStep(stage="gate", action="pass" if holdout_result.passed else "fail")
    ]
    if not holdout_result.passed:
        return PromotionResult(steps=steps, final_status="rejected_gate")

    shadow_passed = shadow_result is not None and shadow_result.passed
    steps.append(PromotionStep(stage="shadow", action="pass" if shadow_passed else "fail"))
    if not shadow_passed:
        return PromotionResult(steps=steps, final_status="rejected_shadow")

    for weight in CANARY_WEIGHTS:
        set_canary_weight(weight)
        if burn_check(weight):
            revert_to_champion()
            steps.append(PromotionStep(stage=f"canary_{weight}", action="revert"))
            return PromotionResult(steps=steps, final_status="rolled_back")
        steps.append(PromotionStep(stage=f"canary_{weight}", action="advance"))

    return PromotionResult(steps=steps, final_status="promoted")
