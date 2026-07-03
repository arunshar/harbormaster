"""Fixture loaders for the CDC tests (Phase 2).

debezium_envelopes.jsonl lines are {"topic", "key", "value"} with key/value as
embedded JSON values (null for a tombstone value). Hand-authored at gate C3 per
the Debezium 2.7 format; re-recorded from the live Strimzi stack at gate C6 and
re-pinned (any diff is a finding, not a silent overwrite). The SHA256 pins in
expectations.json are asserted by cdc/tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
ENVELOPES_PATH = FIXTURES_DIR / "debezium_envelopes.jsonl"
EXPECTATIONS_PATH = FIXTURES_DIR / "expectations.json"


def load_expectations() -> dict:
    return json.loads(EXPECTATIONS_PATH.read_text())


def envelopes_sha256() -> str:
    return hashlib.sha256(ENVELOPES_PATH.read_bytes()).hexdigest()


def load_envelope_messages() -> list[tuple[str, str, str | None]]:
    """Yield (topic, key_json, value_json_or_None) exactly as Kafka would hand them over."""
    out: list[tuple[str, str, str | None]] = []
    for line in ENVELOPES_PATH.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        value = d["value"]
        out.append(
            (
                d["topic"],
                json.dumps(d["key"], separators=(",", ":")),
                None if value is None else json.dumps(value, separators=(",", ":")),
            )
        )
    return out
