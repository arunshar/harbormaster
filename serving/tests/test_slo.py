"""Unit tests for the Phase 1 SLO evaluator (gate G7)."""

from __future__ import annotations

import math

from app.slo import PHASE1_SLOS, all_ok, evaluate


def test_all_slos_pass():
    results = evaluate(
        {"score_success_ratio": 1.0, "score_kernel_p95_ms": 120.0, "replay_to_hitl_p95_s": 4.0}
    )
    assert all_ok(results)
    assert {r.slo.name for r in results} == {s.name for s in PHASE1_SLOS}


def test_latency_breach_flags_only_that_slo():
    results = evaluate(
        {"score_success_ratio": 1.0, "score_kernel_p95_ms": 500.0, "replay_to_hitl_p95_s": 4.0}
    )
    assert not all_ok(results)
    breached = [r.slo.name for r in results if not r.ok]
    assert breached == ["score_kernel_p95_ms"]


def test_success_ratio_below_target_breaches():
    results = evaluate(
        {"score_success_ratio": 0.99, "score_kernel_p95_ms": 100.0, "replay_to_hitl_p95_s": 2.0}
    )
    assert [r.slo.name for r in results if not r.ok] == ["score_success_ratio"]


def test_missing_measurement_breaches_as_nan():
    results = evaluate({"score_success_ratio": 1.0})
    missing = [r for r in results if r.slo.name == "score_kernel_p95_ms"][0]
    assert missing.ok is False
    assert math.isnan(missing.measured)
    assert not all_ok(results)
