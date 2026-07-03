"""Gate C1: the registry DDL is idempotent-shaped, complete, and checksum-pinned."""

from __future__ import annotations

import json
from pathlib import Path

from cdc.schema import ddl

EXPECTATIONS = Path(__file__).parent.parent / "fixtures" / "expectations.json"


def test_all_cdc_tables_are_created_if_not_exists():
    text = ddl.canonical_ddl()
    for table in ddl.CDC_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in text
    assert ddl.CDC_TABLES == ("vessels", "watchlist", "sanctions_flags")


def test_replica_identity_full_on_every_cdc_table():
    text = ddl.canonical_ddl()
    for table in ddl.CDC_TABLES:
        assert f"ALTER TABLE {table} REPLICA IDENTITY FULL;" in text


def test_publication_is_guarded_and_covers_exactly_the_cdc_tables():
    text = ddl.canonical_ddl()
    # Postgres has no CREATE PUBLICATION IF NOT EXISTS; the DO block is the guard.
    assert f"IF NOT EXISTS (\n        SELECT 1 FROM pg_publication WHERE pubname = '{ddl.PUBLICATION_NAME}'" in text  # noqa: E501
    assert f"CREATE PUBLICATION {ddl.PUBLICATION_NAME} FOR TABLE {', '.join(ddl.CDC_TABLES)};" in text  # noqa: E501


def test_every_statement_is_individually_idempotent_shaped():
    for stmt in ddl.statements():
        assert (
            "IF NOT EXISTS" in stmt or "REPLICA IDENTITY" in stmt
        ), f"statement is not re-runnable: {stmt[:60]}"


def test_ddl_sha256_matches_the_pinned_expectation():
    expected = json.loads(EXPECTATIONS.read_text())["ddl_sha256"]
    assert ddl.ddl_sha256() == expected, (
        "the canonical DDL changed; if intentional, update cdc/fixtures/expectations.json "
        "AND docs/phases/PHASE_2.md in the same commit"
    )


def test_sanctions_flag_id_is_deterministic_normalized_and_refuses_blank():
    assert ddl.sanctions_flag_id(367000003, "OFAC") == "367000003:ofac"
    assert ddl.sanctions_flag_id(367000003, "  ofac ") == "367000003:ofac"
    # a blank regime would mint the "<mmsi>:" poison id the CDC key mapper
    # rejects; every id producer refuses it, and the DDL CHECK backstops it
    import pytest

    with pytest.raises(ValueError):
        ddl.sanctions_flag_id(367000003, "   ")
    assert "CHECK (id ~ '^[0-9]+:.')" in ddl.canonical_ddl()


def test_serving_registry_id_helper_stays_in_sync():
    # serving/app/registry.py duplicates the id rule so the wheel does not import
    # cdc at runtime; this test is the drift guard.
    import pytest

    from app.registry import _sanctions_flag_id

    for mmsi, regime in ((1, "OFAC"), (999_999_999, " eu "), (367000003, "UN")):
        assert _sanctions_flag_id(mmsi, regime) == ddl.sanctions_flag_id(mmsi, regime)
    with pytest.raises(ValueError):
        _sanctions_flag_id(1, " ")
