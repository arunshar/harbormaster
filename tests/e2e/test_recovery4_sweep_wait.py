"""Regression tests for the Recovery4 read-only helper's safety gates.

The operator helper at ``artifacts/w4/*-recovery4-readonly/operator-recovery4-readonly.sh``
is a single-use, gitignored operator package. It used to hard-fail before a fixed
00:15 PDT wall clock; it now polls CloudWatch for a complete *wet* invocation whose
start falls inside the configured nightly schedule window. These tests pin that
behavior, the pre-AWS trust ordering, exact Terraform state identity, and unfiltered
network inventory by reading the actual helper and executing its embedded sweep
classifier against synthetic CloudWatch event fixtures.

When the gitignored helper is absent (e.g. a fresh checkout) the test skips, since
there is no tracked artifact to verify.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HELPER_GLOB = "artifacts/w4/*-recovery4-readonly/operator-recovery4-readonly.sh"

# CloudWatch querying opens at 23:55 PDT, while valid starts are 00:00-00:30 PDT.
SWEEP_LOG_QUERY_START_MS = 1785912900000
SWEEP_CANDIDATE_START_MS = 1785913200000
SWEEP_LATEST_START_MS = 1785915000000
REQUEST_ID = "11111111-2222-3333-4444-555555555555"


def _find_helper() -> Path | None:
    configured = os.environ.get("HM_RECOVERY4_HELPER_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    candidates = sorted(REPO.glob(HELPER_GLOB))
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


def _extract_live_state_classifier(helper_text: str) -> str:
    """Return the embedded Python that classifies tracked state against AWS inventory."""
    output_idx = helper_text.find('(root / "live-state-classification.json").write_text')
    assert output_idx != -1, "live-state-classification output not found"
    heredoc_open = helper_text.rfind("<<'PY'", 0, output_idx)
    assert heredoc_open != -1, "live-state classifier python heredoc not found"
    body_start = helper_text.index("\n", heredoc_open) + 1
    body_end = helper_text.find("\nPY\n", output_idx)
    assert body_end != -1, "live-state classifier python heredoc terminator not found"
    return helper_text[body_start:body_end]


def _run_classifier(classifier_src: str, events: list[dict]) -> dict[str, str]:
    fixture = REPO / "artifacts" / "w4" / ".sweep-wait-fixture.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps({"events": events}))
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                classifier_src,
                str(fixture),
                str(SWEEP_CANDIDATE_START_MS),
                str(SWEEP_LATEST_START_MS),
            ],
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
        {"timestamp": start_ts, "message": f"START RequestId: {REQUEST_ID} Version: $LATEST\n"},
        {
            "timestamp": start_ts + 1000,
            "message": json.dumps({"event": "teardown_complete", "dry_run": dry_run})
            + f" {REQUEST_ID}\n",
        },
        {"timestamp": start_ts + 2000, "message": f"END RequestId: {REQUEST_ID}\n"},
        {
            "timestamp": start_ts + 3000,
            "message": f"REPORT RequestId: {REQUEST_ID}\tDuration: 1 ms\n",
        },
    ]


def test_helper_replaced_the_wall_clock_gate():
    assert HELPER is not None
    text = HELPER.read_text()
    assert "wait_for_completed_wet_sweep" in text
    assert text.count("wait_for_completed_wet_sweep") >= 2  # definition + call
    assert "Post-sweep audit is too early" not in text
    assert "SWEEP_POLL_INTERVAL_SEC=" in text
    assert "Wet sweep complete" in text


def test_wait_classifier_accepts_a_complete_wet_invocation_in_the_window():
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    events = _complete_wet_events(dry_run=False, start_ts=SWEEP_CANDIDATE_START_MS + 60_000)
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
    events = _complete_wet_events(dry_run=True, start_ts=SWEEP_CANDIDATE_START_MS + 60_000)
    verdict = _run_classifier(classifier, events)
    assert verdict["valid"] == "0"


def test_wait_classifier_rejects_a_start_outside_the_sweep_window():
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    events = _complete_wet_events(dry_run=False, start_ts=SWEEP_CANDIDATE_START_MS - 10_000)
    verdict = _run_classifier(classifier, events)
    assert verdict["valid"] == "0"


def test_wait_classifier_rejects_a_2355_log_query_only_event():
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    events = _complete_wet_events(dry_run=False, start_ts=SWEEP_LOG_QUERY_START_MS + 10_000)
    verdict = _run_classifier(classifier, events)
    assert verdict["valid"] == "0"


def test_wait_classifier_rejects_a_sweep_that_logged_a_service_failure():
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    events = _complete_wet_events(dry_run=False, start_ts=SWEEP_CANDIDATE_START_MS + 60_000)
    events.insert(
        2,
        {
            "timestamp": events[0]["timestamp"] + 500,
            "message": json.dumps({"event": "eks_delete_failed", "error": "boom"})
            + f" {REQUEST_ID}\n",
        },
    )
    verdict = _run_classifier(classifier, events)
    assert verdict["valid"] == "0"
    assert "service failure" in verdict["reason"]


@pytest.mark.parametrize(
    ("failure_kind", "failure_message"),
    [
        (
            "report",
            f"REPORT RequestId: {REQUEST_ID}\tDuration: 1 ms\t"
            "Status: error\tError Type: Runtime.ExitError\n",
        ),
        ("event", f"Task timed out after 3.00 seconds {REQUEST_ID}\n"),
        ("event", f"Process exited before completing request {REQUEST_ID}\n"),
    ],
)
def test_wait_classifier_rejects_lambda_runtime_failures(failure_kind: str, failure_message: str):
    assert HELPER is not None
    classifier = _extract_wait_classifier(HELPER.read_text())
    events = _complete_wet_events(dry_run=False, start_ts=SWEEP_CANDIDATE_START_MS + 60_000)
    if failure_kind == "report":
        events[-1]["message"] = failure_message
    else:
        events.insert(
            2,
            {
                "timestamp": events[0]["timestamp"] + 500,
                "message": failure_message,
            },
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


def test_helper_rejects_endpoint_overrides_before_the_first_aws_request():
    assert HELPER is not None
    text = HELPER.read_text()
    checksum_gate = text.index("shasum -a 256 -c operator-readonly-inputs.sha256")
    endpoint_guard = text.index("AWS endpoint override variables are set.")
    terraform_guard = text.index("Terraform override variables are set.")
    first_aws = text.index("aws sts get-caller-identity")
    early_lambda_hash = text.index("EARLY_NIGHTLY_LAMBDA_CODE_SHA256=")
    wait_call = text.index("\nwait_for_completed_wet_sweep\n")
    assert checksum_gate < endpoint_guard < first_aws < early_lambda_hash < wait_call
    assert checksum_gate < terraform_guard < first_aws
    for variable in (
        "AWS_ENDPOINT_URL",
        "AWS_CA_BUNDLE",
        "HTTPS_PROXY",
        "TF_CLI_ARGS",
        "TF_DATA_DIR",
    ):
        assert variable in text


def test_helper_pins_exact_caller_and_terraform_state_identity():
    assert HELPER is not None
    text = HELPER.read_text()
    assert "EXPECTED_STATE_SERIAL=69" in text
    assert "EXPECTED_STATE_VERSION_ID=yh2IGBdXC.Arm2lj5maOxXprVlmVejU_" in text
    assert "EXPECTED_STATE_ETAG='\"af97addd80c039890bd689446929d14e\"'" in text
    assert (
        "EXPECTED_NIGHTLY_LAMBDA_CODE_SHA256=OGoIzCLyqF6mZVbQ4OlKWILSI5iT1xFvRB636t8kY40=" in text
    )
    assert 'test "$STATE_OBJECT_VERSION" = "$EXPECTED_STATE_VERSION_ID"' in text
    assert 'if summary["serial"] != expected_serial:' in text
    assert 'state_summary.get("serial") == expected_state_serial' in text
    assert 'state_summary.get("serial") >= 69' not in text
    assert '"source_code_hash": attrs.get("source_code_hash")' in text
    assert '== nightly_lambda_live.get("CodeSha256")' in text
    assert '"nightly_teardown_lambda_code_matches_state": nightly_lambda_code_ok' in text
    caller_guard = 'test "$CALLER_ARN" = "arn:aws:iam::${ACCOUNT_ID}:user/arun-admin"'
    assert caller_guard in text


def test_helper_does_not_overclaim_scheduler_provenance():
    assert HELPER is not None
    text = HELPER.read_text()
    assert text.count("complete wet invocation in the configured nightly schedule window") == 2
    assert text.count("with no logged service failure") == 2
    assert "complete scheduled wet sweep invocation" not in text
    assert "does not claim scheduler provenance" in text


def test_helper_uses_unfiltered_network_inventory_and_checks_orphans():
    assert HELPER is not None
    text = HELPER.read_text()
    assert "capture_optional nat-gateways aws ec2 describe-nat-gateways\n" in text
    assert "capture_optional elastic-ips aws ec2 describe-addresses\n" in text
    assert "capture_optional route-tables aws ec2 describe-route-tables\n" in text
    for filtered_command in (
        "describe-nat-gateways \\\n  --filter",
        "describe-addresses \\\n  --filters",
        "describe-route-tables \\\n  --filters",
    ):
        assert filtered_command not in text
    for needle in (
        "state_nat_gateway_ids",
        "state_eip_ids",
        "state_route_table_ids",
        "live_route_table_ids",
        "state_route_table_ids.issubset(live_route_table_ids)",
        "is_project_base(row)",
        "route_table_inventory_ok",
    ):
        assert needle in text


def test_live_state_classifier_rejects_a_missing_tracked_route_table(tmp_path: Path):
    assert HELPER is not None
    classifier = _extract_live_state_classifier(HELPER.read_text())
    state_instances = [
        {
            "address": "module.network.aws_route.private_nat[0]",
            "mode": "managed",
            "module": "module.network",
            "type": "aws_route",
            "id": "r-rtb-missing1080289494",
            "route_table_id": "rtb-missing",
            "destination_cidr_block": "0.0.0.0/0",
            "nat_gateway_id": "nat-missing",
        }
    ]
    (tmp_path / "state-instances.json").write_text(json.dumps(state_instances))
    (tmp_path / "route-tables.json").write_text(json.dumps({"RouteTables": []}))
    subprocess.run(
        [sys.executable, "-c", classifier, str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = json.loads((tmp_path / "live-state-classification.json").read_text())
    assert rows == [
        {
            "address": "module.network.aws_route.private_nat[0]",
            "classification": "unexpected_absent",
            "state_id": "r-rtb-missing1080289494",
            "type": "aws_route",
        }
    ]
