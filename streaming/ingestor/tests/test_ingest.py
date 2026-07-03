"""Unit tests for the replay ingestor (gate G4). No AWS: put and sleep are injected."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ingestor.ingest import (
    MAX_BYTES_PER_CALL,
    backoff_schedule,
    batch_entries,
    record_to_entry,
    replay,
    sorted_by_time,
)
from replay.loader import AisRecord

T0 = datetime(2024, 6, 1, tzinfo=UTC)


def _rec(mmsi: int, minute: int, lat: float = 40.0, lon: float = -74.0) -> AisRecord:
    return AisRecord(mmsi=mmsi, lat=lat, lon=lon, t=T0 + timedelta(minutes=minute), sog=9.0)


def test_sorted_by_time_orders_ascending():
    recs = [_rec(1, 5), _rec(2, 1), _rec(3, 3)]
    got = [r.t for r in sorted_by_time(recs)]
    assert got == sorted(got)


def test_record_to_entry_partition_key_and_json():
    import json

    e = record_to_entry(_rec(367000001, 0))
    assert e["PartitionKey"] == "367000001"
    payload = json.loads(e["Data"])
    assert payload["mmsi"] == 367000001
    assert payload["t"] == "2024-06-01T00:00:00Z"


def test_batch_entries_respects_record_count_limit():
    entries = [{"Data": b"x", "PartitionKey": "1"} for _ in range(1200)]
    batches = list(batch_entries(entries, max_records=500))
    assert [len(b) for b in batches] == [500, 500, 200]
    assert sum(len(b) for b in batches) == 1200


def test_batch_entries_respects_byte_limit():
    # Each entry ~1 KiB; cap at 4 KiB -> at most 4 per batch.
    entries = [{"Data": b"x" * 1024, "PartitionKey": "1"} for _ in range(10)]
    batches = list(batch_entries(entries, max_records=500, max_bytes=4096))
    assert all(sum(len(e["Data"]) + 1 for e in b) <= 4096 for b in batches)
    assert sum(len(b) for b in batches) == 10


def test_batch_entries_oversize_record_raises():
    import pytest

    entries = [{"Data": b"x" * (MAX_BYTES_PER_CALL + 1), "PartitionKey": "1"}]
    with pytest.raises(ValueError):
        list(batch_entries(entries))


def test_replay_sends_all_records_in_time_order():
    recs = [_rec(1, 5), _rec(2, 1), _rec(3, 3)]
    sent_batches: list[list[dict]] = []
    slept: list[float] = []
    n = replay(recs, put=sent_batches.append, speedup=60.0, sleep=slept.append)

    assert n == 3
    flat = [e for b in sent_batches for e in b]
    assert len(flat) == 3
    # Emitted in ascending-time order (MMSI 2 @1min, 3 @3min, 1 @5min).
    assert [e["PartitionKey"] for e in flat] == ["2", "3", "1"]
    assert all(s >= 0 for s in slept)


def test_replay_no_pacing_when_speedup_zero():
    recs = [_rec(1, 0), _rec(2, 10)]
    slept: list[float] = []
    replay(recs, put=lambda b: None, speedup=0, sleep=slept.append)
    assert slept == []


def test_backoff_schedule_is_capped_exponential():
    assert backoff_schedule(0, base=0.5) == 0.5
    assert backoff_schedule(1, base=0.5) == 1.0
    assert backoff_schedule(2, base=0.5) == 2.0
    assert backoff_schedule(100, base=0.5, cap=30.0) == 30.0
