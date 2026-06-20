# streaming/flink

Flink streaming jobs for Harbormaster's feature plane.

**Lands in:** Phase 1 (Streaming ingestion).

**Will contain:** the Flink application(s), run on Kinesis Data Analytics, that consume normalized AIS from Kinesis Data Streams and compute per-vessel streaming features (event-time windows, keyed per-vessel state, watermarking with bounded out-of-orderness). Output is written to the online feature store (Feast / DynamoDB) and forked to Firehose for the S3/Iceberg lakehouse. War stories P1 (shard hot-partitioning) and P2 (watermark stalls under late AIS) anticipate the failure modes this code will have to handle.

Empty for now. Phase 0 provisions only foundations and FinOps guardrails.
