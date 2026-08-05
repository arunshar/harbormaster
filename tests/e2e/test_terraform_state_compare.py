"""Regression coverage for order-stable Terraform state comparisons."""

from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.compare_terraform_state import (
    ALGORITHM,
    StateComparisonError,
    build_report,
    canonical_state_bytes,
    canonical_state_sha256,
    canonicalize_state,
    load_state,
    load_state_bytes,
    main,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "compare_terraform_state.py"
WITNESS = REPO / "tests" / "e2e" / "fixtures" / "recovery4_check_results_witness.json"


def _base_state() -> dict:
    return {
        "version": 4,
        "terraform_version": "1.15.6",
        "serial": 69,
        "lineage": "419a8985-87a0-4470-0b20-25f2ef23f7d4",
        "outputs": {
            "serving_target": {
                "sensitive": False,
                "type": "string",
                "value": "ecs",
            }
        },
        "resources": [
            {
                "mode": "managed",
                "type": "aws_lambda_function",
                "name": "nightly_teardown",
                "instances": [{"attributes": {"id": "harbormaster-base-nightly-teardown"}}],
            }
        ],
        "check_results": [
            {
                "config_addr": "var.serving_target",
                "object_kind": "var",
                "objects": [
                    {"object_addr": "var.serving_target[1]", "status": "pass"},
                    {"object_addr": "var.serving_target[0]", "status": "pass"},
                ],
                "status": "pass",
            },
            {
                "config_addr": "module.kms.var.environment",
                "object_kind": "var",
                "objects": None,
                "status": "pass",
            },
        ],
    }


def _raw(state: dict) -> bytes:
    return (json.dumps(state, sort_keys=True) + "\n").encode()


def _load_witness() -> dict:
    return json.loads(WITNESS.read_text())


def _witness_checks(witness: dict, order_key: str) -> list[dict]:
    records = {
        config_addr: (object_addr, status)
        for config_addr, object_addr, status in witness["records"]
    }
    return [
        {
            "config_addr": config_addr,
            "object_kind": "var",
            "objects": (
                None
                if records[config_addr][0] is None
                else [
                    {
                        "object_addr": records[config_addr][0],
                        "status": records[config_addr][1],
                    }
                ]
            ),
            "status": records[config_addr][1],
        }
        for config_addr in witness[order_key]
    ]


def test_canonicalizer_sorts_only_order_insensitive_check_collections():
    original = _base_state()
    reordered = copy.deepcopy(original)
    reordered["check_results"].reverse()
    reordered["check_results"][1]["objects"].reverse()

    assert canonical_state_bytes(original) == canonical_state_bytes(reordered)
    assert canonical_state_sha256(original) == canonical_state_sha256(reordered)
    assert original == _base_state(), "canonicalization must not mutate its input"

    canonical = canonicalize_state(reordered)
    assert [row["config_addr"] for row in canonical["check_results"]] == [
        "module.kms.var.environment",
        "var.serving_target",
    ]
    assert [row["object_addr"] for row in canonical["check_results"][1]["objects"]] == [
        "var.serving_target[0]",
        "var.serving_target[1]",
    ]


def test_sanitized_recovery4_witness_reproduces_the_exact_34_record_permutation():
    witness_text = WITNESS.read_text()
    witness = json.loads(witness_text)
    assert set(witness) == {"provenance", "left_order", "right_order", "records"}
    assert set(witness["provenance"]) == {
        "left_raw_sha256",
        "right_raw_sha256",
        "normalized_sha256",
    }
    assert len(witness["records"]) == 34
    assert all(
        isinstance(record, list)
        and len(record) == 3
        and isinstance(record[0], str)
        and (record[1] is None or isinstance(record[1], str))
        and isinstance(record[2], str)
        for record in witness["records"]
    )
    assert len({record[0] for record in witness["records"]}) == 34

    left_checks = _witness_checks(witness, "left_order")
    right_checks = _witness_checks(witness, "right_order")
    assert len(left_checks) == len(right_checks) == 34
    assert all(left != right for left, right in zip(left_checks, right_checks, strict=True))
    assert {row["config_addr"] for row in left_checks} == {
        row["config_addr"] for row in right_checks
    }

    left_state = _base_state()
    right_state = _base_state()
    left_state["check_results"] = left_checks
    right_state["check_results"] = right_checks

    assert canonical_state_bytes(left_state) == canonical_state_bytes(right_state)
    assert sum(row["status"] == "pass" for row in left_checks) == 31
    assert sum(row["status"] == "unknown" for row in left_checks) == 3
    assert sum(len(row["objects"] or []) for row in left_checks) == 33
    assert all(
        set(check) == {"config_addr", "object_kind", "objects", "status"}
        for check in left_checks + right_checks
    )
    assert all(
        set(row) == {"object_addr", "status"}
        for check in left_checks + right_checks
        for row in check["objects"] or []
    )
    for forbidden in (
        '"resources"',
        '"outputs"',
        '"attributes"',
        "arn:",
        "645322802947",
        "access_key",
        "credential",
        "password",
        "secret",
        "session_token",
    ):
        assert forbidden not in witness_text.lower()


@pytest.mark.parametrize(
    "mutation",
    [
        "serial",
        "lineage",
        "resource",
        "output",
        "check_status",
        "object_status",
        "config_addr",
        "object_addr",
        "missing_check",
        "additional_check",
        "additional_object",
        "null_to_empty_objects",
        "unrelated_array_order",
    ],
)
def test_canonicalizer_preserves_semantic_differences(mutation: str):
    baseline = _base_state()
    changed = copy.deepcopy(baseline)

    if mutation == "serial":
        changed["serial"] += 1
    elif mutation == "lineage":
        changed["lineage"] = "different-lineage"
    elif mutation == "resource":
        changed["resources"][0]["instances"][0]["attributes"]["id"] = "different"
    elif mutation == "output":
        changed["outputs"]["serving_target"]["value"] = "eks"
    elif mutation == "check_status":
        changed["check_results"][0]["status"] = "fail"
    elif mutation == "object_status":
        changed["check_results"][0]["objects"][0]["status"] = "fail"
    elif mutation == "config_addr":
        changed["check_results"][0]["config_addr"] = "var.changed"
    elif mutation == "object_addr":
        changed["check_results"][0]["objects"][0]["object_addr"] = "var.changed"
    elif mutation == "missing_check":
        changed["check_results"].pop()
    elif mutation == "additional_check":
        changed["check_results"].append(
            {
                "config_addr": "var.enable_phase5",
                "object_kind": "var",
                "objects": [],
                "status": "pass",
            }
        )
    elif mutation == "additional_object":
        changed["check_results"][0]["objects"].append(
            {"object_addr": "var.serving_target[2]", "status": "pass"}
        )
    elif mutation == "null_to_empty_objects":
        changed["check_results"][1]["objects"] = []
    elif mutation == "unrelated_array_order":
        changed["resources"].append(
            {"mode": "managed", "type": "aws_s3_bucket", "name": "state", "instances": []}
        )
        baseline["resources"].append(copy.deepcopy(changed["resources"][1]))
        changed["resources"].reverse()
    else:  # pragma: no cover
        raise AssertionError(f"unknown mutation: {mutation}")

    assert canonical_state_bytes(baseline) != canonical_state_bytes(changed)


@pytest.mark.parametrize(
    ("checks", "message"),
    [
        (None, "must be an array"),
        ({}, "must be an array"),
        ([None], "entry 0 must be a JSON object"),
        (
            [{"object_kind": "var", "status": "pass", "objects": []}],
            "non-empty config_addr",
        ),
        (
            [
                {
                    "config_addr": " ",
                    "object_kind": "var",
                    "status": "pass",
                    "objects": [],
                }
            ],
            "non-empty config_addr",
        ),
        (
            [
                {
                    "config_addr": "var.a",
                    "object_kind": "var",
                    "status": "pass",
                    "objects": [],
                },
                {
                    "config_addr": "var.a",
                    "object_kind": "var",
                    "status": "pass",
                    "objects": [],
                },
            ],
            "duplicate check_results config_addr",
        ),
        (
            [{"config_addr": "var.a", "object_kind": "var", "status": "pass"}],
            "must contain objects",
        ),
        (
            [
                {
                    "config_addr": "var.a",
                    "object_kind": "var",
                    "status": "pass",
                    "objects": {},
                }
            ],
            "objects must be null or an array",
        ),
        (
            [
                {
                    "config_addr": "var.a",
                    "object_kind": "var",
                    "status": "pass",
                    "objects": [None],
                }
            ],
            "object 0 must be a JSON object",
        ),
        (
            [
                {
                    "config_addr": "var.a",
                    "object_kind": "var",
                    "status": "pass",
                    "objects": [{}],
                }
            ],
            "non-empty object_addr",
        ),
        (
            [
                {
                    "config_addr": "var.a",
                    "object_kind": "var",
                    "status": "pass",
                    "objects": [
                        {"object_addr": "var.a", "status": "pass"},
                        {"object_addr": "var.a", "status": "pass"},
                    ],
                }
            ],
            "duplicate object_addr",
        ),
    ],
)
def test_canonicalizer_rejects_ambiguous_check_shapes(checks, message: str):
    state = _base_state()
    state["check_results"] = checks
    with pytest.raises(StateComparisonError, match=message):
        canonical_state_bytes(state)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("object_kind", None),
        ("object_kind", ""),
        ("status", None),
        ("status", ""),
    ],
)
def test_canonicalizer_requires_check_metadata(field: str, value):
    state = _base_state()
    state["check_results"][0][field] = value
    with pytest.raises(StateComparisonError, match=f"non-empty {field}"):
        canonical_state_bytes(state)


def test_canonicalizer_requires_nested_object_status():
    state = _base_state()
    del state["check_results"][0]["objects"][0]["status"]
    with pytest.raises(StateComparisonError, match="non-empty status"):
        canonical_state_bytes(state)


@pytest.mark.parametrize("version", [None, True, 3, 4.0, 5, "4"])
def test_canonicalizer_requires_exact_state_version(version):
    state = _base_state()
    state["version"] = version
    with pytest.raises(StateComparisonError, match="version must be exactly 4"):
        canonical_state_bytes(state)


def test_canonicalizer_requires_check_results():
    state = _base_state()
    del state["check_results"]
    with pytest.raises(StateComparisonError, match="must contain check_results"):
        canonical_state_bytes(state)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("terraform_version", None, "non-empty terraform_version"),
        ("terraform_version", "", "non-empty terraform_version"),
        ("serial", None, "serial must be a non-negative integer"),
        ("serial", True, "serial must be a non-negative integer"),
        ("serial", 1.0, "serial must be a non-negative integer"),
        ("serial", -1, "serial must be a non-negative integer"),
        ("lineage", None, "non-empty lineage"),
        ("lineage", "", "non-empty lineage"),
        ("outputs", None, "outputs must be a JSON object"),
        ("outputs", [], "outputs must be a JSON object"),
        ("resources", None, "resources must be an array"),
        ("resources", {}, "resources must be an array"),
    ],
)
def test_canonicalizer_requires_complete_typed_state_shape(field, value, message: str):
    state = _base_state()
    state[field] = value
    with pytest.raises(StateComparisonError, match=message):
        canonical_state_bytes(state)


@pytest.mark.parametrize(
    "field",
    ["terraform_version", "serial", "lineage", "outputs", "resources"],
)
def test_canonicalizer_rejects_missing_top_level_state_fields(field: str):
    state = _base_state()
    del state[field]
    with pytest.raises(StateComparisonError):
        canonical_state_bytes(state)


def _state_with_number(number: str, location: str) -> bytes:
    state = {
        "version": 4,
        "terraform_version": "1.15.6",
        "serial": 69,
        "lineage": "419a8985-87a0-4470-0b20-25f2ef23f7d4",
        "outputs": {},
        "resources": [],
        "check_results": [],
    }
    payload = json.dumps(state, separators=(",", ":"))
    if location == "output":
        replacement = '"outputs":{"witness":{"value":' + number + "}}"
        return payload.replace('"outputs":{}', replacement).encode()
    if location == "resource":
        replacement = '"resources":[{"instances":[{"attributes":{"value":' + number + "}}]}]"
        return payload.replace('"resources":[]', replacement).encode()
    if location == "check":
        replacement = (
            '"check_results":[{"config_addr":"var.witness","object_kind":"var",'
            '"objects":null,"status":"pass","numeric_witness":' + number + "}]"
        )
        return payload.replace('"check_results":[]', replacement).encode()
    raise AssertionError(f"unknown number location: {location}")


@pytest.mark.parametrize(
    ("location", "left_number", "right_number"),
    [
        ("output", "9007199254740992.0", "9007199254740993.0"),
        (
            "resource",
            "0.1234567890123456789012345678901",
            "0.1234567890123456789012345678902",
        ),
        ("check", "1e400", "1e401"),
    ],
)
def test_lossless_number_comparison_preserves_distinct_values(
    location: str, left_number: str, right_number: str
):
    left = load_state_bytes(_state_with_number(left_number, location))
    right = load_state_bytes(_state_with_number(right_number, location))

    assert canonical_state_bytes(left) != canonical_state_bytes(right)


@pytest.mark.parametrize(
    ("location", "left_number", "right_number"),
    [
        ("output", "1e3", "1000.0"),
        ("resource", "1e3", "1000.0"),
        ("check", "1e3", "1000.0"),
        ("output", "-0.0", "0"),
    ],
)
def test_lossless_number_comparison_normalizes_equivalent_json_numbers(
    location: str, left_number: str, right_number: str
):
    left = load_state_bytes(_state_with_number(left_number, location))
    right = load_state_bytes(_state_with_number(right_number, location))

    assert canonical_state_bytes(left) == canonical_state_bytes(right)


def test_canonicalizer_rejects_binary_float_values_from_direct_callers():
    state = _base_state()
    state["outputs"]["binary_float"] = {"value": 0.1}

    with pytest.raises(StateComparisonError, match="binary floating-point"):
        canonical_state_bytes(state)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (Decimal("NaN"), "non-finite decimal"),
        ({1: "not-a-json-key"}, "keys must be strings"),
        ({"not", "a", "json", "value"}, "unsupported JSON value type"),
    ],
)
def test_canonicalizer_rejects_non_json_values_from_direct_callers(value, message: str):
    state = _base_state()
    state["outputs"]["invalid"] = {"value": value}

    with pytest.raises(StateComparisonError, match=message):
        canonical_state_bytes(state)


def _run_main(left: Path, right: Path, report: Path, capsys) -> tuple[int, str, str]:
    return_code = main([str(left), str(right), str(report)])
    captured = capsys.readouterr()
    return return_code, captured.out, captured.err


def test_cli_reports_equivalent_states_without_copying_state_values(tmp_path: Path, capsys):
    left_state = _base_state()
    right_state = copy.deepcopy(left_state)
    right_state["check_results"].reverse()
    left_state["outputs"]["private_marker"] = {"value": "DO-NOT-COPY", "sensitive": True}
    right_state["outputs"]["private_marker"] = {"value": "DO-NOT-COPY", "sensitive": True}
    left = tmp_path / "s3-state.json"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "comparison.json"
    left.write_bytes(_raw(left_state))
    right.write_bytes(_raw(right_state))
    report.write_text("old")
    report.chmod(0o644)

    return_code, stdout, stderr = _run_main(left, right, report, capsys)

    assert return_code == 0, stderr
    assert stdout == ""
    assert stderr == ""
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    parsed = json.loads(report.read_text())
    assert parsed["algorithm"] == ALGORITHM
    assert parsed["equivalent"] is True
    assert parsed["reason"] == "equivalent"
    assert parsed["left"]["normalized_sha256"] == parsed["right"]["normalized_sha256"]
    assert "DO-NOT-COPY" not in report.read_text()


def test_cli_returns_one_and_writes_a_hash_only_mismatch_report(tmp_path: Path, capsys):
    left_state = _base_state()
    right_state = copy.deepcopy(left_state)
    right_state["outputs"]["serving_target"]["value"] = "PRIVATE-DIFFERENCE"
    left = tmp_path / "s3-state.json"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "comparison.json"
    left.write_bytes(_raw(left_state))
    right.write_bytes(_raw(right_state))

    return_code, stdout, stderr = _run_main(left, right, report, capsys)

    assert return_code == 1
    assert stdout == ""
    assert stderr == ""
    parsed = json.loads(report.read_text())
    assert parsed["equivalent"] is False
    assert parsed["reason"] == "normalized_state_mismatch"
    assert parsed["left"]["normalized_sha256"] != parsed["right"]["normalized_sha256"]
    assert "PRIVATE-DIFFERENCE" not in report.read_text()


@pytest.mark.parametrize(
    "invalid_payload",
    [
        b'{"version": 4, "version": 5, "check_results": []}',
        b'{"version": 4, "check_results": [], "value": NaN}',
        b'[{"version": 4, "check_results": []}]',
        _state_with_number("1e1000000000000000000", "output"),
        _state_with_number("9" * 5000, "output"),
        b"[" * 2000 + b"0" + b"]" * 2000,
    ],
)
def test_cli_rejects_invalid_json_without_replacing_the_report(
    tmp_path: Path, invalid_payload: bytes, capsys
):
    left = tmp_path / "s3-state.json"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "comparison.json"
    left.write_bytes(invalid_payload)
    right.write_bytes(_raw(_base_state()))
    report.write_text("preserved")

    return_code, stdout, stderr = _run_main(left, right, report, capsys)

    assert return_code == 2
    assert stdout == ""
    assert "state comparison failed" in stderr
    assert "Traceback" not in stderr
    assert report.read_text() == "preserved"


def test_duplicate_key_failure_does_not_echo_the_key(tmp_path: Path, capsys):
    left = tmp_path / "s3-state.json"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "comparison.json"
    private_key = "PRIVATE-STATE-MAP-KEY"
    left.write_bytes(
        (
            '{"version":4,"terraform_version":"1.15.6","serial":69,'
            '"lineage":"lineage","outputs":{},"resources":[],"check_results":[],'
            f'"{private_key}":1,"{private_key}":2}}'
        ).encode()
    )
    right.write_bytes(_raw(_base_state()))

    return_code, _, stderr = _run_main(left, right, report, capsys)

    assert return_code == 2
    assert "duplicate JSON object key" in stderr
    assert private_key not in stderr
    assert not report.exists()


@pytest.mark.parametrize("failure", ["private_config_addr", "private_object_addr"])
def test_state_derived_addresses_never_reach_cli_output_or_report(
    tmp_path: Path, capsys, failure: str
):
    private_config = "var.PRIVATE-STATE-CONFIG"
    private_object = "var.PRIVATE-STATE-OBJECT"
    state = _base_state()
    if failure == "private_config_addr":
        state["check_results"][0]["config_addr"] = private_config
        del state["check_results"][0]["objects"]
    else:
        state["check_results"][0]["objects"] = [
            {"object_addr": private_object, "status": "pass"},
            {"object_addr": private_object, "status": "pass"},
        ]

    left = tmp_path / "s3-state.json"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "comparison.json"
    left.write_bytes(_raw(state))
    right.write_bytes(_raw(_base_state()))

    return_code, stdout, stderr = _run_main(left, right, report, capsys)

    assert return_code == 2
    combined = stdout + stderr + (report.read_text() if report.exists() else "")
    assert private_config not in combined
    assert private_object not in combined


@pytest.mark.parametrize("overlap", ["left-right", "left-report", "right-report"])
def test_cli_rejects_overlapping_paths(tmp_path: Path, capsys, overlap: str):
    left = tmp_path / "s3-state.json"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "comparison.json"
    left.write_bytes(_raw(_base_state()))
    right.write_bytes(_raw(_base_state()))
    if overlap == "left-right":
        right = left
    elif overlap == "left-report":
        report = left
    elif overlap == "right-report":
        report = right

    return_code, _, stderr = _run_main(left, right, report, capsys)

    assert return_code == 2
    assert "must be distinct" in stderr


@pytest.mark.parametrize("hardlink_target", ["right", "report"])
def test_cli_rejects_hardlinked_paths(tmp_path: Path, capsys, hardlink_target: str):
    left = tmp_path / "s3-state.json"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "comparison.json"
    left.write_bytes(_raw(_base_state()))
    if hardlink_target == "right":
        os.link(left, right)
    else:
        right.write_bytes(_raw(_base_state()))
        os.link(left, report)

    return_code, _, stderr = _run_main(left, right, report, capsys)

    assert return_code == 2
    assert "must be distinct" in stderr


def test_cli_fails_closed_when_a_state_file_is_missing(tmp_path: Path, capsys):
    missing = tmp_path / "missing.tfstate"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "comparison.json"
    right.write_bytes(_raw(_base_state()))

    return_code, _, stderr = _run_main(missing, right, report, capsys)

    assert return_code == 2
    assert "state comparison failed" in stderr
    assert not report.exists()


def test_cli_fails_closed_when_report_directory_is_missing(tmp_path: Path, capsys):
    left = tmp_path / "s3-state.json"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "missing" / "comparison.json"
    left.write_bytes(_raw(_base_state()))
    right.write_bytes(_raw(_base_state()))

    return_code, _, stderr = _run_main(left, right, report, capsys)

    assert return_code == 2
    assert "report directory does not exist" in stderr
    assert not report.exists()


def test_isolated_cli_entrypoint_writes_an_equivalent_report(tmp_path: Path):
    left = tmp_path / "s3-state.json"
    right = tmp_path / "terraform.tfstate"
    report = tmp_path / "comparison.json"
    left.write_bytes(_raw(_base_state()))
    right.write_bytes(_raw(_base_state()))

    result = subprocess.run(
        [sys.executable, "-I", "-B", str(SCRIPT), str(left), str(right), str(report)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(report.read_text())["equivalent"] is True


def test_report_builder_records_only_hashes_counts_and_reason():
    left_state = _base_state()
    right_state = copy.deepcopy(left_state)
    right_state["check_results"].reverse()
    report = build_report(_raw(left_state), left_state, _raw(right_state), right_state)

    assert set(report) == {"algorithm", "equivalent", "reason", "left", "right"}
    assert set(report["left"]) == {
        "check_object_count",
        "check_result_count",
        "normalized_sha256",
        "raw_sha256",
    }
    assert report["left"]["check_result_count"] == 2
    assert report["left"]["check_object_count"] == 2


def test_captured_recovery4_pair_when_explicitly_requested():
    configured = os.environ.get("HM_RECOVERY4_STATE_DIR")
    if not configured:
        pytest.skip("set HM_RECOVERY4_STATE_DIR to verify the consumed local capture")

    artifact_dir = Path(configured)
    left_raw, left_state = load_state(artifact_dir / "s3-state-object.json")
    right_raw, right_state = load_state(artifact_dir / "terraform.tfstate")
    report = build_report(left_raw, left_state, right_raw, right_state)
    witness = _load_witness()
    provenance = witness["provenance"]

    assert report["equivalent"] is True
    assert left_state["check_results"] == _witness_checks(witness, "left_order")
    assert right_state["check_results"] == _witness_checks(witness, "right_order")
    assert report["left"]["check_result_count"] == 34
    assert report["right"]["check_result_count"] == 34
    assert report["left"]["raw_sha256"] == provenance["left_raw_sha256"]
    assert report["right"]["raw_sha256"] == provenance["right_raw_sha256"]
    assert report["left"]["normalized_sha256"] == provenance["normalized_sha256"]
    assert report["left"]["normalized_sha256"] == canonical_state_sha256(right_state)
