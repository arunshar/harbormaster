# streaming/flink

Flink streaming jobs for Harbormaster's feature plane.

**Lands in:** Phase 1 (Streaming ingestion). The AWS-deployed Flink app (Kinesis
Data Analytics) is built at gate G5 and needs the AWS account (it consumes Kinesis,
writes DynamoDB + S3, and calls the serving ALB).

**Implemented now (local, no AWS):** the per-vessel feature functions the Flink
keyed-window operator computes live as a pure, unit-tested library at
`../features/` (`haversine`, `gap_since_last_s`, `v_required_mps`, and the
`p_physical` cheap-gate pinned to the 25 kt vessel cap). The Flink job will call
these on each 1-minute tumbling window; keeping them as a plain library lets them
test without a Flink runtime, and a test asserts the feature `v_max` equals the
serving config exactly. The recorded AIS replay source the job consumes lives at
`../fixtures/ais_recorded.jsonl` with a reader at `../replay/loader.py`.

**Will contain:** the Flink application(s) that consume normalized AIS from Kinesis
Data Streams, compute the features above with event-time windows / watermarking,
write to the online feature store (DynamoDB), async-IO call `POST /v1/score-ais`,
and tee enriched events to Firehose for the S3/Iceberg lakehouse. War stories P1
(shard hot-partitioning) and P2 (watermark stalls under late AIS) anticipate the
failure modes this code will handle.
