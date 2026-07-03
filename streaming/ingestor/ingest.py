"""Replay ingestor (Phase 1.4, gate G4).

Reads the recorded AIS fixture (from S3 or a local path), replays it in
timestamp order at ~10x real time, and PutRecords in batches to the ais-raw
Kinesis stream with partitionKey = MMSI (so a vessel's fixes stay ordered on one
shard). Dual-mode via env: MODE=REPLAY (default) reads the fixture; the live
AISStream websocket path (AIS_LIVE=true) is wired at gate 1.9. The pure helpers
(ordering, batching, backoff) are unit-tested without AWS; boto3 is imported
lazily so the tests need no cloud.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from replay.loader import AisRecord, load_fixture

# Kinesis PutRecords hard limits.
MAX_RECORDS_PER_CALL = 500
MAX_BYTES_PER_CALL = 5 * 1024 * 1024  # 5 MiB

# A PutRecords entry: {"Data": bytes, "PartitionKey": str}.
KinesisEntry = dict


def sorted_by_time(records: Sequence[AisRecord]) -> list[AisRecord]:
    """Replay order: ascending timestamp, MMSI as a stable tiebreak."""
    return sorted(records, key=lambda r: (r.t, r.mmsi))


def record_to_entry(r: AisRecord) -> KinesisEntry:
    """Map one AIS record to a PutRecords entry (compact JSON, MMSI partition key)."""
    payload = {
        "mmsi": r.mmsi,
        "lat": r.lat,
        "lon": r.lon,
        "t": r.t.isoformat().replace("+00:00", "Z"),
        "sog": r.sog,
        "cog": r.cog,
        "heading": r.heading,
    }
    data = json.dumps(payload, separators=(",", ":")).encode()
    return {"Data": data, "PartitionKey": str(r.mmsi)}


def _entry_size(e: KinesisEntry) -> int:
    # Kinesis counts the data blob plus the partition key toward the 5 MB cap.
    return len(e["Data"]) + len(e["PartitionKey"].encode())


def batch_entries(
    entries: Sequence[KinesisEntry],
    max_records: int = MAX_RECORDS_PER_CALL,
    max_bytes: int = MAX_BYTES_PER_CALL,
) -> Iterator[list[KinesisEntry]]:
    """Chunk entries into PutRecords-legal batches (<= max_records and <= max_bytes)."""
    batch: list[KinesisEntry] = []
    size = 0
    for e in entries:
        es = _entry_size(e)
        if es > max_bytes:
            raise ValueError(f"single record is {es} bytes, over the {max_bytes}-byte cap")
        if batch and (len(batch) >= max_records or size + es > max_bytes):
            yield batch
            batch, size = [], 0
        batch.append(e)
        size += es
    if batch:
        yield batch


def backoff_schedule(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """Exponential backoff (seconds), capped, for the live-mode reconnect loop (gate 1.9)."""
    return min(cap, base * (2 ** max(0, attempt)))


def replay(
    records: Sequence[AisRecord],
    put: Callable[[list[KinesisEntry]], None],
    speedup: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Replay records in time order, pacing inter-batch gaps by 1/speedup, and
    PutRecords in Kinesis-legal batches. Returns the count sent. `put` and `sleep`
    are injected so tests run with no AWS and no real delay. speedup <= 0 blasts
    with no pacing (used by the fast smoke test)."""
    ordered = sorted_by_time(records)
    entries = [record_to_entry(r) for r in ordered]
    times = [r.t for r in ordered]
    prev_t = None
    sent = 0
    for batch in batch_entries(entries):
        first_t = times[sent]  # sent is the index of this batch's first entry
        if prev_t is not None and speedup > 0:
            gap = (first_t - prev_t).total_seconds() / speedup
            if gap > 0:
                sleep(gap)
        put(batch)
        sent += len(batch)
        prev_t = times[sent - 1]
    return sent


# --------------------------------------------------------------------------
# Runtime wiring (only exercised in the container; not imported by the tests)
# --------------------------------------------------------------------------


def _name_from_arn(arn: str) -> str:
    # arn:aws:kinesis:<region>:<acct>:stream/<name> -> <name>
    return arn.split("/", 1)[-1]


def _load_records() -> list[AisRecord]:
    """Load the fixture from FIXTURE_URI (s3://bucket/key or a local path); default
    to the bundled local fixture for a laptop run."""
    uri = os.environ.get("FIXTURE_URI", "")
    if uri.startswith("s3://"):
        import tempfile

        import boto3

        bucket, key = uri[len("s3://") :].split("/", 1)
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        with tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False) as f:
            f.write(body)
            tmp = f.name
        return load_fixture(tmp)
    return load_fixture(Path(uri)) if uri else load_fixture()


def _kinesis_putter(client, stream_name: str) -> Callable[[list[KinesisEntry]], None]:
    def put(batch: list[KinesisEntry]) -> None:
        resp = client.put_records(StreamName=stream_name, Records=batch)
        if resp.get("FailedRecordCount", 0):
            # Retry only the failed records once (partial-failure is normal at load).
            retry = [
                batch[i]
                for i, rec in enumerate(resp["Records"])
                if rec.get("ErrorCode")
            ]
            if retry:
                client.put_records(StreamName=stream_name, Records=retry)

    return put


def main() -> None:
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    stream = os.environ.get("KINESIS_STREAM_NAME") or _name_from_arn(
        os.environ["KINESIS_STREAM_ARN"]
    )
    put = _kinesis_putter(boto3.client("kinesis", region_name=region), stream)

    if os.environ.get("AIS_LIVE", "").lower() == "true":
        from ingestor.live import real_open_stream, run_live

        api_key = os.environ["AISSTREAM_API_KEY"]
        n = run_live(
            lambda: real_open_stream(api_key),
            lambda rec: put([record_to_entry(rec)]),
            time.sleep,
        )
        print(f"live: streamed {n} records to {stream}")
        return

    speedup = float(os.environ.get("REPLAY_SPEEDUP", "10"))
    sent = replay(_load_records(), put, speedup=speedup)
    print(f"replayed {sent} records to {stream}")


if __name__ == "__main__":
    main()
