"""Integration test for the Recovery4 read-only helper's sweep-completion wait gate.

The operator helper at ``artifacts/w4/*-recovery4-readonly/operator-recovery4-readonly.sh``
is a single-use, gitignored operator package. It used to hard-fail before a fixed
00:15 PDT wall clock; it now polls CloudWatch for a complete *wet* nightly sweep
before proceeding. This test pins that behavior by reading the actual helper when
it is present on disk, asserting the wall-clock gate was removed, and executing
the embedded sweep classifier against synthetic CloudWatch event fixtures.

When the gitignored helper is absent (e.g. a fresh checkout) the test skips, since
there is no tracked artifact to verify.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HELPER_GLOB = "artifacts/w4/*-recovery4-readonly/operator-recovery4-readonly.sh"

# The scheduled wet sweep window the helper pins (23:55-00:30 PDT, 2026-08-05).
SWEEP_START_MS = 1785912900000
SWEEP_LATEST_START_MS = 1785915000000
REQUEST_ID = "11111111-2222-3333-4444-555555555555"


def _find_helper() -> Path | None:
    candidates = sorted((REPO).glob(HELPER_GLOB))
    return candidates[0] if candidates else None


HELPER = _find_helper()

pytestmark = pytest.mark.skipif(
    HELPER is None,
    reason="recovery4-readonly operator helper is not present (gitignored, single-use)",
)


def _extract_wait_classifier(helper_text: str) -> str:
    """Return the first embedded Python classifier after wait_for_completed_wet_sweep()."""
    func_idx = helper_text.find("wait_for_completed_wet_sweep()")
    assert func_idx != -1, "wait_for_completed_wet_sweep() definition not found"
    heredoc_open = helper_text.find("<<'PY'", func_idx)
    assert heredoc_open != -1, "wait-loop python heredoc not found"
    body_start = helper_text.index("\n", heredoc_open) + 1
    body_end = helper_text.find("\nPY\n", body_start)
    assert body_end != -1, "wait-loop python heredoc terminator not found"
    return helper_text[body_start:body_end]


def _run_classifier(classifier_src: str, events: list[dict]) -> dict[str, str]:
    fixture = REPO / "artifacts" / "w4" / ".sweep-wait-fixture.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps({"events": events}))
    try:
        result = subprocess.run(
            [sys.executable, "-c", classifier_src, str(fixture),
             str(SWEEP_START_MS), str(SWEEP_LATEST_START_MS)],
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        fixture.unlink(missing_ok=True)
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            parsed[key.strip()] = value.strip()
    return parsed


def _complete_wet_events(dry_run: bool, start_ts: int) -> list[dict]:
    return [
        {"timestamp": start_ts,
         "message": f"START RequestId: {REQUEST_ID} Version: $LATEST\n"},
        {"timestamp": start_ts + 1000,
         "message": json.dumps(
             {"event": "teardown_complete", "dry_run": dry_run}
         ) + f" {REQUEST_ID}\n"},
        {"timestamp": start_ts + 2000,
         "message": f"END RequestId: {REQUEST_ID}\n"},
        {"timestamp": start_ts + 3000,
         "message": f"REPORT RequestId: {REQUEST_ID}\tDuration: 1 ms\n"},
    ]


def test_helper_replaced_the_wall_clock_gate():
    assert HELPER is not None
    text = HELPER.read_text()
    assert "wait_for_completed_wet_sweep" in text
    assert text.count("wait_for_completed_wet_sweep") >= 2  # definition + call
    assert "Post-sweep audit is too early" not in text
    assert "SWEEP_POLL_INTERVAL_SEC=" in text
    assert "Wet sweep complete" in text


def test_wait_classifier_accepts_a_complete_wet_sweep():
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    events = _complete_wet_events(dry_run=False, start_ts=SWEEP_START_MS + 60_000)
    verdict = _run_classifier(classifier, events)
    assert verdict["valid"] == "1"
    assert "no logged service failure" in verdict["reason"]


def test_wait_classifier_rejects_empty_events():
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    verdict = _run_classifier(classifier, [])
    assert verdict["valid"] == "0"


def test_wait_classifier_rejects_a_dry_run_sweep():
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    events = _complete_wet_events(dry_run=True, start_ts=SWEEP_START_MS + 60_000)
    verdict = _run_classifier(classifier, events)
    assert verdict["valid"] == "0"


def test_wait_classifier_rejects_a_start_outside_the_sweep_window():
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    events = _complete_wet_events(dry_run=False, start_ts=SWEEP_START_MS - 10_000)
    verdict = _run_classifier(classifier, events)
    assert verdict["valid"] == "0"


def test_wait_classifier_rejects_a_sweep_that_logged_a_service_failure():
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    events = _complete_wet_events(dry_run=False, start_ts=SWEEP_START_MS + 60_000)
    events.insert(
        2,
        {"timestamp": events[0]["timestamp"] + 500,
         "message": json.dumps(
             {"event": "eks_delete_failed", "error": "boom"}
         ) + f" {REQUEST_ID}\n"},
    )
    verdict = _run_classifier(classifier, events)
    assert verdict["valid"] == "0"
    assert "service failure" in verdict["reason"]


def test_wait_classifier_preserves_the_downstream_verdict_contract():
    """The wait loop and the captured nightly-sweep-verdict share the same criteria."""
    assert HELPER is not None
    text = HELPER.read_text()
    wait_classifier = _extract_wait_classifier(text)
    verdict_idx = text.find('"$ARTIFACT_DIR/nightly-sweep-verdict.json"')
    assert verdict_idx != -1
    verdict_open = text.find("<<'PY'", verdict_idx)
    verdict_body_start = text.index("\n", verdict_open) + 1
    verdict_body_end = text.find("\nPY\n", verdict_body_start)
    verdict_classifier = text[verdict_body_start:verdict_body_end]
    # Both classifiers must key on the same wet-completion signal.
    for needle in ('"dry_run"\\s*:\\s*false', "teardown_complete", "REPORT RequestId:"):
        assert needle in wait_classifier, needle
        assert needle in verdict_classifier, needle
