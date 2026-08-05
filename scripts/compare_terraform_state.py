#!/usr/bin/env python3
"""Compare Terraform state without treating check-result order as drift."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Any

ALGORITHM = "terraform-state-v4-check-results-address-sort-lossless-v1"


class StateComparisonError(ValueError):
    """The input cannot be compared without weakening state integrity."""


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StateComparisonError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise StateComparisonError(f"nonstandard JSON number: {value}")


def _parse_json_decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except DecimalException as error:
        raise StateComparisonError("JSON decimal is outside the supported range") from error


def _parse_json_integer(value: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise StateComparisonError("JSON integer is outside the supported range") from error


def load_state_bytes(payload: bytes) -> dict[str, Any]:
    """Parse JSON without silently accepting duplicate keys or non-finite numbers."""
    state = json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_nonstandard_constant,
        parse_float=_parse_json_decimal,
        parse_int=_parse_json_integer,
    )
    if not isinstance(state, dict):
        raise StateComparisonError("Terraform state root must be a JSON object")
    return state


def load_state(path: Path) -> tuple[bytes, dict[str, Any]]:
    payload = path.read_bytes()
    return payload, load_state_bytes(payload)


def _required_string(row: dict[str, Any], key: str, context: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StateComparisonError(f"{context} must contain a non-empty {key}")
    return value


def _normalize_check_objects(check: dict[str, Any], context: str) -> None:
    if "objects" not in check:
        raise StateComparisonError(f"{context} must contain objects")

    objects = check["objects"]
    if objects is None:
        return
    if not isinstance(objects, list):
        raise StateComparisonError(f"{context} objects must be null or an array")

    seen: set[str] = set()
    for index, row in enumerate(objects):
        if not isinstance(row, dict):
            raise StateComparisonError(f"{context} object {index} must be a JSON object")
        object_addr = _required_string(
            row,
            "object_addr",
            f"{context} object {index}",
        )
        _required_string(
            row,
            "status",
            f"{context} object {index}",
        )
        if object_addr in seen:
            raise StateComparisonError(f"{context} has duplicate object_addr")
        seen.add(object_addr)

    check["objects"] = sorted(objects, key=lambda row: row["object_addr"])


def canonicalize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy a state and order only Terraform's check-result collections."""
    version = state.get("version")
    if type(version) is not int or version != 4:
        raise StateComparisonError("Terraform state version must be exactly 4")
    terraform_version = state.get("terraform_version")
    if not isinstance(terraform_version, str) or not terraform_version.strip():
        raise StateComparisonError("Terraform state must contain a non-empty terraform_version")
    serial = state.get("serial")
    if type(serial) is not int or serial < 0:
        raise StateComparisonError("Terraform state serial must be a non-negative integer")
    lineage = state.get("lineage")
    if not isinstance(lineage, str) or not lineage.strip():
        raise StateComparisonError("Terraform state must contain a non-empty lineage")
    if not isinstance(state.get("outputs"), dict):
        raise StateComparisonError("Terraform state outputs must be a JSON object")
    if not isinstance(state.get("resources"), list):
        raise StateComparisonError("Terraform state resources must be an array")
    if "check_results" not in state:
        raise StateComparisonError("Terraform state must contain check_results")
    checks = state["check_results"]
    if not isinstance(checks, list):
        raise StateComparisonError("Terraform state check_results must be an array")

    canonical = copy.deepcopy(state)
    canonical_checks = canonical["check_results"]
    seen: set[str] = set()
    for index, check in enumerate(canonical_checks):
        if not isinstance(check, dict):
            raise StateComparisonError(f"check_results entry {index} must be a JSON object")
        context = f"check_results entry {index}"
        config_addr = _required_string(check, "config_addr", context)
        _required_string(check, "object_kind", context)
        _required_string(check, "status", context)
        if config_addr in seen:
            raise StateComparisonError("duplicate check_results config_addr")
        seen.add(config_addr)
        _normalize_check_objects(check, context)

    canonical["check_results"] = sorted(canonical_checks, key=lambda row: row["config_addr"])
    return canonical


def _canonical_number(value: int | Decimal) -> list[Any]:
    try:
        decimal = Decimal(value)
    except DecimalException as error:
        raise StateComparisonError("numeric value is outside the supported range") from error
    if not decimal.is_finite():
        raise StateComparisonError("non-finite decimal value cannot be compared")
    if decimal.is_zero():
        return [0, "0", 0]
    parts = decimal.as_tuple()
    digits = list(parts.digits)
    exponent = parts.exponent
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    return [parts.sign, "".join(str(digit) for digit in digits), exponent]


def _comparison_tree(value: Any) -> list[Any]:
    """Encode JSON values with explicit type tags and lossless numeric values."""
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["boolean", value]
    if type(value) is int or isinstance(value, Decimal):
        return ["number", _canonical_number(value)]
    if isinstance(value, float):
        raise StateComparisonError("binary floating-point values cannot be compared safely")
    if isinstance(value, str):
        return ["string", value]
    if isinstance(value, list):
        return ["array", [_comparison_tree(item) for item in value]]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise StateComparisonError("JSON object keys must be strings")
        return [
            "object",
            [[key, _comparison_tree(value[key])] for key in sorted(value)],
        ]
    raise StateComparisonError(f"unsupported JSON value type: {type(value).__name__}")


def canonical_state_bytes(state: dict[str, Any]) -> bytes:
    """Serialize the validated state deterministically without exposing it."""
    canonical = canonicalize_state(state)
    payload = json.dumps(
        _comparison_tree(canonical),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (payload + "\n").encode()


def canonical_state_sha256(state: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_state_bytes(state)).hexdigest()


def _check_counts(canonical: dict[str, Any]) -> tuple[int, int]:
    checks = canonical["check_results"]
    object_count = sum(
        len(check["objects"]) for check in checks if isinstance(check["objects"], list)
    )
    return len(checks), object_count


def build_report(
    left_raw: bytes,
    left_state: dict[str, Any],
    right_raw: bytes,
    right_state: dict[str, Any],
) -> dict[str, Any]:
    """Build a hash-only report after both state shapes pass strict validation."""
    left_canonical = canonicalize_state(left_state)
    right_canonical = canonicalize_state(right_state)
    left_bytes = canonical_state_bytes(left_canonical)
    right_bytes = canonical_state_bytes(right_canonical)
    left_checks, left_objects = _check_counts(left_canonical)
    right_checks, right_objects = _check_counts(right_canonical)
    equivalent = left_bytes == right_bytes
    return {
        "algorithm": ALGORITHM,
        "equivalent": equivalent,
        "reason": "equivalent" if equivalent else "normalized_state_mismatch",
        "left": {
            "check_object_count": left_objects,
            "check_result_count": left_checks,
            "normalized_sha256": hashlib.sha256(left_bytes).hexdigest(),
            "raw_sha256": hashlib.sha256(left_raw).hexdigest(),
        },
        "right": {
            "check_object_count": right_objects,
            "check_result_count": right_checks,
            "normalized_sha256": hashlib.sha256(right_bytes).hexdigest(),
            "raw_sha256": hashlib.sha256(right_raw).hexdigest(),
        },
    }


def _write_private_report(path: Path, report: dict[str, Any]) -> None:
    if not path.parent.is_dir():
        raise StateComparisonError(f"report directory does not exist: {path.parent}")
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two Terraform v4 states and write a private hash-only report."
    )
    parser.add_argument("left", type=Path, help="first raw Terraform state JSON")
    parser.add_argument("right", type=Path, help="second raw Terraform state JSON")
    parser.add_argument("report", type=Path, help="mode-600 comparison report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        resolved = [args.left.resolve(), args.right.resolve(), args.report.resolve()]
        if len(set(resolved)) != 3:
            raise StateComparisonError("both state paths and the report path must be distinct")
        existing_paths = [path for path in (args.left, args.right, args.report) if path.exists()]
        if any(
            os.path.samefile(left, right)
            for index, left in enumerate(existing_paths)
            for right in existing_paths[index + 1 :]
        ):
            raise StateComparisonError("both state files and the report must be distinct")
        left_raw, left_state = load_state(args.left)
        right_raw, right_state = load_state(args.right)
        report = build_report(left_raw, left_state, right_raw, right_state)
        _write_private_report(args.report, report)
    except (
        DecimalException,
        OSError,
        OverflowError,
        RecursionError,
        UnicodeError,
        ValueError,
    ) as error:
        print(f"state comparison failed: {error}", file=sys.stderr)
        return 2
    return 0 if report["equivalent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
