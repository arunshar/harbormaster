# ADR 0001: Streaming plane is a per-event keyed realization, not an event-time windowed pipeline

**Status:** Accepted

**Date:** 2026-07-06

## Context

`streaming/flink/job.py` keys `ais-raw` by MMSI and, in a `KeyedProcessFunction`, computes window features against the previous fix held in `ValueState`, gates on `p_physical`, writes the gated item to DynamoDB, and POSTs the serving scorer. This is per-event processing against keyed prev-state, not a true event-time tumbling window with watermarks and checkpointed window state. The docstring says so: "A true 1-minute event-time tumbling window can replace the per-fix keyed process below." The `.print()` tail is evidence-of-processing in CloudWatch logs, not the output path; the DynamoDB write and scorer POST are side effects inside `process_element`.

## Decision

Ship the streaming plane as a per-event keyed realization for the demo, on standard portable PyFlink APIs. Defer a real event-time tumbling window (watermarks, checkpointed window state) as optional future work, adopted only if late-fix correctness becomes a hard requirement.

## Consequences

Positive: portable, minimal state per key, and it drove out real first-live-run Managed Flink findings (W1, 2026-07-04): dependency-staging bugs, the `application_properties.json` config path, the `_j_function` sink restriction, DynamoDB float/TTL handling, and the scorer's history/schema contract. Negative and honestly labeled: no watermark handling, so out-of-order and late fixes are not reconciled the way a windowed job would; correctness rests on delivery order plus prev-state. Managed Flink event-time windowing is delegated to AWS and is currently untested here; adopting it is deferred, not proven.

## Alternatives considered

**True event-time tumbling window (watermarks + checkpoints).** The correct model for out-of-order and late AIS, and the stated replacement. Deferred: it adds checkpoint and watermark tuning and a heavier state backend, and Managed Flink windowing is untested in this build. Not needed for the demo's correctness bar.

**Spark Structured Streaming.** Rejected in ARCHITECTURE.md: micro-batch adds latency and makes per-vessel event-time logic harder than Flink's keyed state and timers.
