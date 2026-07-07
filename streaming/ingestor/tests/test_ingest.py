"""Unit tests for the replay ingestor (gate G4). No AWS: put and sleep are injected."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from ingestor.ingest import (
    MAX_BYTES_PER_CALL,
    PUT_BASE_DELAY,
    PUT_DELAY_CAP,
    _kinesis_putter,
    backoff_schedule,
    batch_entries,
    jittered_backoff,
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


# --------------------------------------------------------------------------
# Kinesis PutRecords retry: bounded exponential backoff with full jitter.
# No AWS: the boto3 kinesis client is a Mock; time.sleep is captured, not real.
# --------------------------------------------------------------------------


def test_jittered_backoff_within_capped_exponential_window():
    # Full jitter draws uniformly in [0, min(cap, base * 2**attempt)].
    rng = random.Random(0)
    for attempt in range(8):
        ceiling = min(PUT_DELAY_CAP, PUT_BASE_DELAY * (2**attempt))
        d = jittered_backoff(attempt, base=PUT_BASE_DELAY, cap=PUT_DELAY_CAP, rng=rng)
        assert 0.0 <= d <= ceiling
    # The window itself grows exponentially then saturates at the cap.
    assert jittered_backoff(0, base=1.0, cap=100.0, rng=random.Random(1)) <= 1.0
    assert jittered_backoff(100, base=1.0, cap=5.0, rng=random.Random(1)) <= 5.0


def _ok_response(n: int) -> dict:
    return {"FailedRecordCount": 0, "Records": [{"SequenceNumber": str(i)} for i in range(n)]}


def _partial_failure_response(n_total: int, failed_idx: set[int]) -> dict:
    records = []
    for i in range(n_total):
        if i in failed_idx:
            records.append({"ErrorCode": "ProvisionedThroughputExceededException"})
        else:
            records.append({"SequenceNumber": str(i)})
    return {"FailedRecordCount": len(failed_idx), "Records": records}


def _throttling_client_error():
    from botocore.exceptions import ClientError

    return ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
        "PutRecords",
    )


def _entries(n: int) -> list[dict]:
    return [{"Data": b"x", "PartitionKey": str(i)} for i in range(n)]


def test_kinesis_putter_retries_partial_failures_then_succeeds(monkeypatch):
    # First call: records 1 and 2 fail. Retry: only those two, and both succeed.
    client = Mock()
    client.put_records.side_effect = [
        _partial_failure_response(3, failed_idx={1, 2}),
        _ok_response(2),
    ]
    slept: list[float] = []
    put = _kinesis_putter(
        client, "ais-raw", sleep=slept.append, rng=random.Random(1234)
    )

    put(_entries(3))

    assert client.put_records.call_count == 2
    # The retry resubmits only the two still-failing records (indexes 1 and 2).
    retry_records = client.put_records.call_args_list[1].kwargs["Records"]
    assert [r["PartitionKey"] for r in retry_records] == ["1", "2"]
    # Exactly one backoff between the two attempts, and it was a positive delay.
    assert len(slept) == 1
    assert slept[0] > 0


def test_kinesis_putter_retries_throttling_clienterror_then_succeeds(monkeypatch):
    # Whole-call throttling twice, then success. Backoff is increasing per attempt.
    client = Mock()
    client.put_records.side_effect = [
        _throttling_client_error(),
        _throttling_client_error(),
        _ok_response(2),
    ]
    slept: list[float] = []
    # Deterministic rng that returns the top of each jitter window so delays are
    # strictly increasing and comparable (window grows as base * 2**attempt).
    top_rng = Mock()
    top_rng.uniform.side_effect = lambda _lo, hi: hi
    put = _kinesis_putter(client, "ais-raw", base_delay=0.1, sleep=slept.append, rng=top_rng)

    put(_entries(2))

    assert client.put_records.call_count == 3
    assert len(slept) == 2
    assert slept[1] > slept[0]  # exponential growth of the backoff window


def test_kinesis_putter_non_retriable_clienterror_raises_immediately():
    from botocore.exceptions import ClientError

    client = Mock()
    client.put_records.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "PutRecords"
    )
    slept: list[float] = []
    put = _kinesis_putter(client, "ais-raw", sleep=slept.append, rng=random.Random(0))

    with pytest.raises(ClientError):
        put(_entries(2))
    assert client.put_records.call_count == 1  # not retried
    assert slept == []


def test_kinesis_putter_gives_up_after_max_retries_and_surfaces_error():
    # Throttling on every call: after max_retries the error is surfaced (re-raised).
    from botocore.exceptions import ClientError

    client = Mock()
    # 1 initial attempt + 3 retries = 4 throttling errors; each is auto-raised
    # because side_effect is an iterable of exception instances.
    client.put_records.side_effect = [_throttling_client_error() for _ in range(4)]
    slept: list[float] = []
    put = _kinesis_putter(
        client, "ais-raw", max_retries=3, sleep=slept.append, rng=random.Random(7)
    )

    with pytest.raises(ClientError):
        put(_entries(2))
    # 1 initial attempt + 3 retries = 4 calls; 3 backoffs before giving up.
    assert client.put_records.call_count == 4
    assert len(slept) == 3


def test_kinesis_putter_gives_up_partial_failures_after_max_retries():
    # Persistent partial failure: bounded attempts, then drop the stuck records
    # (prior behavior) rather than loop forever. No exception on this path.
    client = Mock()
    client.put_records.side_effect = lambda **_kw: _partial_failure_response(2, {0, 1})
    slept: list[float] = []
    put = _kinesis_putter(
        client, "ais-raw", max_retries=2, sleep=slept.append, rng=random.Random(0)
    )

    put(_entries(2))  # returns without raising

    assert client.put_records.call_count == 3  # 1 + 2 retries
    assert len(slept) == 2


def test_kinesis_putter_success_path_unchanged_no_sleep():
    client = Mock()
    client.put_records.return_value = _ok_response(3)
    slept: list[float] = []
    put = _kinesis_putter(client, "ais-raw", sleep=slept.append, rng=random.Random(0))

    put(_entries(3))

    assert client.put_records.call_count == 1
    assert slept == []  # no backoff on the happy path
