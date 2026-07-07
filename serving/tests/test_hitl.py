"""HITL queue tests (Phase 1.2). Memory backend mirrors the Postgres row schema.

A live-Postgres integration test runs only when HM_TEST_PG_DSN is set.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from app.errors import HitlTraceNotFound
from app.hitl import MemoryHitlBackend, PostgresHitlBackend
from app.models import AisScoreOut, FeedbackIn, ReasonCode, ScoreReason

TS = datetime(2024, 6, 1, 3, 20, tzinfo=UTC)


def _out(trace_id: str = "trace-1") -> AisScoreOut:
    return AisScoreOut(
        mmsi=367000003,
        score=1.0,
        confidence=1.0,
        reasons=[ScoreReason(code=ReasonCode.OFF_CORRIDOR, severity=1.0, detail="10 km off lane")],
        hitl_required=True,
        trace_id=trace_id,
        latency_ms=0.5,
        n_history=120,
    )


async def test_enqueue_writes_a_row_with_schema_fields():
    backend = MemoryHitlBackend()
    await backend.enqueue("trace-1", _out(), TS)
    rows = await backend.rows()
    assert len(rows) == 1
    r = rows[0]
    schema_fields = (
        "id", "trace_id", "mmsi", "ts", "score",
        "reasons", "confidence", "label", "reviewer", "created_at",
    )
    for field in schema_fields:
        assert field in r
    assert r["trace_id"] == "trace-1"
    assert r["mmsi"] == 367000003
    assert r["label"] is None
    assert isinstance(r["reasons"], list) and r["reasons"][0]["code"] == "off_corridor"


async def test_enqueue_is_idempotent_on_trace_id():
    backend = MemoryHitlBackend()
    await backend.enqueue("trace-1", _out(), TS)
    await backend.enqueue("trace-1", _out(), TS)  # redelivery
    assert len(await backend.rows()) == 1


async def test_label_updates_row_and_counts_pending():
    backend = MemoryHitlBackend()
    await backend.enqueue("trace-1", _out("trace-1"), TS)
    await backend.enqueue("trace-2", _out("trace-2"), TS)
    fb = FeedbackIn(trace_id="trace-1", label="correct", reviewer="arun")
    remaining = await backend.label(fb)
    assert remaining == 1
    assert len(await backend.pending()) == 1


async def test_label_unknown_trace_raises():
    backend = MemoryHitlBackend()
    await backend.enqueue("trace-1", _out("trace-1"), TS)
    with pytest.raises(HitlTraceNotFound):
        await backend.label(FeedbackIn(trace_id="ghost", label="correct", reviewer="arun"))


@pytest.mark.postgres
@pytest.mark.skipif(not os.getenv("HM_TEST_PG_DSN"), reason="set HM_TEST_PG_DSN to run")
async def test_postgres_backend_enqueue_and_label():
    backend = await PostgresHitlBackend.connect(os.environ["HM_TEST_PG_DSN"])
    try:
        await backend.enqueue("trace-pg-1", _out("trace-pg-1"), TS)
        await backend.enqueue("trace-pg-1", _out("trace-pg-1"), TS)  # ON CONFLICT DO NOTHING
        pending = await backend.pending()
        assert any(r["trace_id"] == "trace-pg-1" for r in pending)
        await backend.label(FeedbackIn(trace_id="trace-pg-1", label="correct", reviewer="arun"))
    finally:
        await backend.close()
