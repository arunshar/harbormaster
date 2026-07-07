"""Shadow-diff comparator (Phase 3, gate 3.7).

Compares the SageMaker shadow ProductionVariant's scores (sampled on live
traffic, discarded from the response per DR-3's "parallel run, no production
effect") against the champion's on the same events. "Clean" means the mean
absolute divergence stays under a threshold over the shadow window; this is
the check that catches training-serving skew (drill 3.8-L1), which the
holdout gate alone cannot see since it evaluates the candidate against the
same offline-encoded holdout set the skew itself would have produced.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ShadowDiffResult:
    mean_abs_diff: float
    max_abs_diff: float
    n_samples: int
    passed: bool


def score_diff(
    champion_scores: np.ndarray, shadow_scores: np.ndarray, *, max_divergence: float
) -> ShadowDiffResult:
    champion_scores = np.asarray(champion_scores, dtype=float)
    shadow_scores = np.asarray(shadow_scores, dtype=float)
    if len(champion_scores) != len(shadow_scores):
        raise ValueError("champion and shadow score arrays must be paired 1:1, same length")
    if len(champion_scores) == 0:
        raise ValueError("score_diff needs at least one paired sample")

    diffs = np.abs(champion_scores - shadow_scores)
    mean_diff = float(np.mean(diffs))
    return ShadowDiffResult(
        mean_abs_diff=mean_diff,
        max_abs_diff=float(np.max(diffs)),
        n_samples=len(diffs),
        passed=mean_diff <= max_divergence,
    )
