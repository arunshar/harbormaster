"""Unit tests for the Flink job's pure window logic (gate G5).

These functions were extracted verbatim out of job.py (which imports pyflink at
module top and so cannot be imported here) into the sibling window_logic module,
which imports NO pyflink. That extraction is what makes this suite possible: the
functions job.py runs per vessel are now importable and testable without a Flink
runtime or AWS. Tests are hermetic (no network, no clock, seeded, deterministic).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from flink.window_logic import (
    P_PHYS_GATE,
    VESSEL_V_MAX_MPS,
    Fix,
    WindowFeatures,
    feature_item,
    gap_since_last_s,
    haversine_m,
    passes_gate,
    post_scorer_with_retry,
    quarantine_envelope,
    v_required_mps,
    window_features,
)

T0 = datetime(2024, 6, 1, tzinfo=UTC)


def test_first_window_has_zero_inter_fix_features():
    # No previous fix (vessel's first window): the inter-fix features are all zero
    # and p_physical is a benign 1.0 (nothing to contradict). The current fix's own
    # instantaneous fields (sog/cog/heading) still pass through.
    wf = window_features(Fix(40.5, -73.9, T0, sog=10.0, cog=90.0, heading=88.0), None)
    assert wf.gap_since_last_s == 0.0
    assert wf.distance_m == 0.0
    assert wf.v_required_mps == 0.0
    assert wf.p_physical == 1.0
    assert (wf.sog, wf.cog, wf.heading) == (10.0, 90.0, 88.0)


def test_non_first_window_computes_expected_features():
    # A ~0.01 deg latitude step (~1112 m) over exactly 60 s: distance, gap, and the
    # required speed are all derivable in closed form, so assert the exact values
    # (not just inequalities). ~1112 m / 60 s ~ 18.5 m/s exceeds the 12.86 m/s cap,
    # so p_physical drops below 1.0 by exactly v_max / v_required.
    prev = Fix(40.50, -73.90, T0)
    curr = Fix(40.51, -73.90, T0 + timedelta(minutes=1))
    wf = window_features(curr, prev)

    expected_dist = haversine_m(40.50, -73.90, 40.51, -73.90)
    expected_gap = gap_since_last_s(T0, T0 + timedelta(minutes=1))
    expected_vreq = v_required_mps(expected_dist, expected_gap)

    assert wf.gap_since_last_s == 60.0
    assert wf.distance_m == pytest.approx(expected_dist)
    assert wf.v_required_mps == pytest.approx(expected_vreq)
    assert wf.v_required_mps > VESSEL_V_MAX_MPS
    assert wf.p_physical == pytest.approx(VESSEL_V_MAX_MPS / expected_vreq)
    assert wf.p_physical < 1.0


def test_passes_gate_at_above_and_below_threshold_boundary():
    # Build features whose p_physical sits exactly on, just above, and just below
    # the gate, and assert the >= boundary (at threshold passes).
    at = WindowFeatures(None, None, None, 0.0, 0.0, 0.0, P_PHYS_GATE)
    above = WindowFeatures(None, None, None, 0.0, 0.0, 0.0, P_PHYS_GATE + 1e-9)
    below = WindowFeatures(None, None, None, 0.0, 0.0, 0.0, P_PHYS_GATE - 1e-9)

    assert passes_gate(at) is True  # gate is inclusive (>=)
    assert passes_gate(above) is True
    assert passes_gate(below) is False

    # explicit threshold argument is honored the same way
    feats = WindowFeatures(None, None, None, 0.0, 0.0, 0.0, 0.5)
    assert passes_gate(feats, 0.5) is True
    assert passes_gate(feats, 0.5 + 1e-9) is False


def test_feature_item_shape_ttl_and_key_fields():
    feats = window_features(Fix(40.5, -73.9, T0, sog=10.0, cog=90.0, heading=88.0), None)
    item = feature_item(367000001, feats, T0, ttl_days=7)

    # key fields for the Feast online (DynamoDB) table
    assert item["entity_id"] == "367000001"
    assert item["feature_name"] == "window"
    assert item["t"] == "2024-06-01T00:00:00Z"
    # ttl is derived from the event timestamp + the retention window
    assert item["ttl"] == int(T0.timestamp()) + 7 * 86400
    # feature payload mirrors the WindowFeatures fields
    assert item["gap_since_last_s"] == feats.gap_since_last_s
    assert item["distance_m"] == feats.distance_m
    assert item["v_required_mps"] == feats.v_required_mps
    assert item["p_physical"] == feats.p_physical
    assert (item["sog"], item["cog"], item["heading"]) == (10.0, 90.0, 88.0)
    # exact key set (no stray fields leak into the item)
    assert set(item) == {
        "entity_id",
        "feature_name",
        "t",
        "gap_since_last_s",
        "distance_m",
        "v_required_mps",
        "p_physical",
        "sog",
        "cog",
        "heading",
        "ttl",
    }
    # ttl_days scales the retention window linearly
    assert feature_item(367000001, feats, T0, ttl_days=1)["ttl"] == int(T0.timestamp()) + 86400


def test_deterministic_on_repeated_calls():
    # Same inputs must yield identical outputs across repeated calls: the functions
    # are pure (no clock, no randomness, no shared mutable state).
    prev = Fix(40.50, -73.90, T0)
    curr = Fix(40.51, -73.90, T0 + timedelta(minutes=1))

    first = window_features(curr, prev)
    second = window_features(curr, prev)
    assert first == second  # frozen dataclass equality is field-wise

    item_a = feature_item(367000001, first, T0)
    item_b = feature_item(367000001, second, T0)
    assert item_a == item_b

    assert passes_gate(first) == passes_gate(second)


# --- Streaming robustness: quarantine (DLQ) envelope ------------------------


def test_quarantine_envelope_wraps_raw_reason_and_timestamp():
    env = quarantine_envelope('{"bad":true}', "parse_error: missing mmsi", T0)
    assert env["raw"] == '{"bad":true}'
    assert env["reason"] == "parse_error: missing mmsi"
    assert env["quarantined_at"] == "2024-06-01T00:00:00Z"


def test_quarantine_envelope_decodes_bytes_payload():
    env = quarantine_envelope(b'{"x":1}', "scorer_post_failed: boom", T0)
    assert env["raw"] == '{"x":1}'  # bytes decoded to text so the DLQ record is readable


def test_quarantine_envelope_handles_undecodable_bytes():
    # Invalid UTF-8 must not raise; the DLQ record preserves what it can (never lose
    # the fact that a bad record arrived) rather than crashing the operator.
    env = quarantine_envelope(b"\xff\xfe not utf8", "parse_error: bad bytes", T0)
    assert isinstance(env["raw"], str)
    assert "not utf8" in env["raw"]


# --- Streaming robustness: bounded, non-blocking scorer retry ---------------


def test_post_scorer_success_first_try_no_retry_no_sleep():
    slept: list[float] = []
    errors: list[tuple[int, Exception]] = []
    calls = {"n": 0}

    def send():
        calls["n"] += 1

    ok, err = post_scorer_with_retry(
        send, sleep=slept.append, on_error=lambda a, e: errors.append((a, e))
    )
    assert ok is True
    assert err is None
    assert calls["n"] == 1  # no retry on the happy path
    assert slept == []  # and no backoff
    assert errors == []  # nothing logged


def test_post_scorer_retries_then_succeeds():
    # Fails once (transient), then succeeds: one logged error, one backoff, success.
    slept: list[float] = []
    errors: list[tuple[int, Exception]] = []
    seq = [RuntimeError("timeout"), None]

    def send():
        exc = seq.pop(0)
        if exc is not None:
            raise exc

    ok, err = post_scorer_with_retry(
        send,
        max_retries=2,
        sleep=slept.append,
        on_error=lambda a, e: errors.append((a, e)),
    )
    assert ok is True
    assert err is None
    assert len(errors) == 1  # the single failure was logged, not swallowed
    assert errors[0][0] == 0  # attempt index 0
    assert len(slept) == 1  # exactly one bounded backoff before the successful retry
    assert slept[0] > 0


def test_post_scorer_exhausts_retries_and_reports_failure_for_dlq():
    # Always fails: bounded attempts, every failure logged, then (False, last_error)
    # so the caller dead-letters. It must NOT raise into the Flink operator.
    slept: list[float] = []
    errors: list[tuple[int, Exception]] = []
    boom = ConnectionError("scorer down")

    def send():
        raise boom

    ok, err = post_scorer_with_retry(
        send,
        max_retries=2,
        sleep=slept.append,
        on_error=lambda a, e: errors.append((a, e)),
    )
    assert ok is False
    assert err is boom  # the last error is returned for the DLQ envelope
    assert len(errors) == 3  # 1 initial + 2 retries, each logged
    assert len(slept) == 2  # backoff only BETWEEN attempts, not after the last
    assert all(s >= 0 for s in slept)


def test_post_scorer_backoff_is_bounded_and_capped():
    # The default backoff grows exponentially but is capped, so retries stay fast and
    # a slow scorer cannot stall the operator (delays never exceed the cap).
    from flink.window_logic import SCORER_DELAY_CAP_S

    slept: list[float] = []

    def send():
        raise TimeoutError("slow")

    post_scorer_with_retry(send, max_retries=8, sleep=slept.append)
    assert len(slept) == 8
    assert all(0 <= s <= SCORER_DELAY_CAP_S for s in slept)
    # Non-decreasing then saturating at the cap (capped exponential).
    assert slept == sorted(slept)


def test_post_scorer_never_raises_even_without_error_callback():
    # No on_error provided: failures are still handled internally and the function
    # returns cleanly (the operator is never taken down by a scorer exception).
    def send():
        raise RuntimeError("boom")

    ok, err = post_scorer_with_retry(send, max_retries=1, sleep=lambda _s: None)
    assert ok is False
    assert isinstance(err, RuntimeError)


def test_post_scorer_negative_retries_makes_no_attempt():
    # Guard on the degenerate config max_retries < 0: the loop body never runs, so
    # send() is never called and the function returns a benign "no attempt" result
    # instead of raising or blocking.
    calls = {"n": 0}

    def send():
        calls["n"] += 1

    ok, err = post_scorer_with_retry(send, max_retries=-1, sleep=lambda _s: None)
    assert (ok, err) == (False, None)
    assert calls["n"] == 0
