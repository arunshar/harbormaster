"""Phase 1 SLOs (gate G7).

The service-level objectives the Phase 1 slice is held to, plus a pure evaluator
that turns measured numbers into pass/breach verdicts. The e2e acceptance test
(1.8) and the dashboard narrative use these; targets mirror PHASE_1.md 1.7.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Compare(StrEnum):
    LTE = "<="  # measured must be <= target
    GTE = ">="  # measured must be >= target


@dataclass(frozen=True)
class Slo:
    name: str
    target: float
    compare: Compare
    unit: str


PHASE1_SLOS: tuple[Slo, ...] = (
    Slo("score_success_ratio", 0.999, Compare.GTE, "ratio"),
    Slo("score_kernel_p95_ms", 300.0, Compare.LTE, "ms"),
    Slo("replay_to_hitl_p95_s", 10.0, Compare.LTE, "s"),
)


@dataclass(frozen=True)
class SloResult:
    slo: Slo
    measured: float
    ok: bool


def evaluate(
    measurements: dict[str, float], slos: tuple[Slo, ...] = PHASE1_SLOS
) -> list[SloResult]:
    """Turn measured values into pass/breach results. A missing measurement breaches."""
    out: list[SloResult] = []
    for slo in slos:
        if slo.name not in measurements:
            out.append(SloResult(slo, float("nan"), ok=False))
            continue
        m = measurements[slo.name]
        ok = m <= slo.target if slo.compare is Compare.LTE else m >= slo.target
        out.append(SloResult(slo, m, ok=ok))
    return out


def all_ok(results: list[SloResult]) -> bool:
    return all(r.ok for r in results)
