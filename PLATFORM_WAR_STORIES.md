# Platform war stories

A running log of real debugging episodes from building Harbormaster. The point is not to look clever; it is to record the wrong turn honestly, because the wrong first hypothesis is usually the most useful part.

## Format

Every entry follows the same five beats:

1. **Symptom:** what was observed, with the concrete signal (an error, a metric, a bill line, a stuck pipeline).
2. **Wrong first hypothesis:** what I initially believed and acted on, before the evidence corrected me.
3. **Root cause:** what was actually happening.
4. **Fix:** the specific change that resolved it.
5. **Lesson:** the generalizable takeaway.

## Tagging

Each entry is tagged so the provenance and the nature of the bug are unambiguous:

- **[PLATFORM / personal-build]:** a Harbormaster (personal) episode. This is the default for everything in this file.
- **[ESRI / company]:** would mark anything originating in the ESRI engagement. Per `docs/HONESTY.md`, ESRI work is kept separate and is NOT logged here; this tag exists only to make the boundary explicit. No entry in this file carries it.
- **CONCURRENCY:** race conditions, ordering, backpressure, state coordination.
- **CORRECTNESS:** wrong results, data loss, schema or semantics bugs.
- **TOOLING:** provider, build, IaC, dependency, or environment issues.

## Grounding rule

An entry graduates from ANTICIPATED to grounded only when it is backed by a real artifact: a commit hash, a log excerpt, or a `file:line` reference from the actual build. Until then it is clearly marked "ANTICIPATED, not yet hit; to be grounded in a real artifact once the build reaches it." Anticipated entries are predictions of where the build will bite, written in advance so they can be confirmed or corrected against reality. No anticipated entry is presented as something that already happened.

---

## P1: Kinesis shard hot-partitioning on vessel MMSI

**Tags:** [PLATFORM / personal-build] CONCURRENCY

**Status:** ANTICIPATED, not yet hit; to be grounded in a real artifact once the build reaches it.

- **Symptom:** one Kinesis shard runs hot and throttles (`ProvisionedThroughputExceededException`) while sibling shards sit nearly idle; end-to-end feature latency spikes for a subset of vessels.
- **Wrong first hypothesis:** the stream is under-provisioned overall; add more shards.
- **Root cause:** the partition key is a coarse region code, so a few dense shipping lanes map all their traffic onto one shard. Total throughput is fine; the key distribution is skewed.
- **Fix:** repartition on a higher-cardinality key (MMSI-derived hash) so per-vessel traffic spreads evenly, and add a hot-key metric so skew is visible before it throttles.
- **Lesson:** shard count treats a symptom; partition-key cardinality is the disease. Always graph per-shard, not just aggregate, throughput.

## P2: Flink event-time windows never fire under late AIS

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status:** ANTICIPATED, not yet hit; to be grounded in a real artifact once the build reaches it.

- **Symptom:** per-vessel feature windows in Flink stop emitting; the online feature store goes stale even though raw events keep arriving.
- **Wrong first hypothesis:** the Flink job is wedged or the sink is down; restart it.
- **Root cause:** watermarks stall because a handful of vessels emit far-future or far-past timestamps, dragging the watermark and preventing windows from closing. The job is healthy; the watermark strategy is wrong.
- **Fix:** add bounded-out-of-orderness with an idleness timeout, clamp obviously bogus timestamps at ingest, and route clamped records to a side output for inspection.
- **Lesson:** in event-time streaming, a stuck pipeline is usually a watermark problem, not a liveness problem. Guard the watermark against adversarial timestamps.

## P3: Debezium snapshot locks the RDS source during initial CDC

**Tags:** [PLATFORM / personal-build] CONCURRENCY

**Status:** ANTICIPATED, not yet hit; to be grounded in a real artifact once the build reaches it.

- **Symptom:** when CDC is first enabled, queries against the operational RDS Postgres slow sharply and the connector takes a long time to reach streaming mode.
- **Wrong first hypothesis:** RDS is undersized; scale the instance up.
- **Root cause:** the default Debezium snapshot reads the whole table set before streaming, holding contention against live traffic; the bottleneck is the snapshot strategy, not instance size.
- **Fix:** switch to an incremental snapshot, confirm `wal_level=logical` and replica identity are set correctly, and schedule the initial snapshot for a low-traffic window.
- **Lesson:** CDC has a cold-start cost. Plan the snapshot like a migration, not a config toggle.

## P4: SageMaker async endpoint silently drops bursts

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status:** ANTICIPATED, not yet hit; to be grounded in a real artifact once the build reaches it.

- **Symptom:** during traffic bursts, some Pi-DPM inference requests produce no result and no error surfaces to the caller.
- **Wrong first hypothesis:** the model container is crashing on certain inputs.
- **Root cause:** the async endpoint's internal queue overflows past its limit and silently sheds requests; without the failure-path SNS notification configured, the drops are invisible.
- **Fix:** wire the async endpoint's success and failure SNS topics, set autoscaling on the backlog-per-instance metric, and make the caller treat "no result within SLA" as an explicit retry, not a success.
- **Lesson:** async means a queue, and a queue means a drop policy. If you have not configured the failure notification, you are losing requests blind.

## P5: DynamoDB online store throttles on cold feature reads

**Tags:** [PLATFORM / personal-build] CONCURRENCY

**Status:** ANTICIPATED, not yet hit; to be grounded in a real artifact once the build reaches it.

- **Symptom:** the GeoTrace front door sees elevated p99 latency and `ProvisionedThroughputExceeded` on first lookups for vessels not seen recently.
- **Wrong first hypothesis:** the table needs a fixed higher provisioned capacity.
- **Root cause:** bursty, spiky read patterns against a provisioned-capacity table; cold vessels arrive in clusters that exceed the steady provisioning.
- **Fix:** move the online store to on-demand capacity (or add autoscaling with a burst buffer), and add a short-TTL cache in the front door for hot vessels.
- **Lesson:** match capacity mode to access pattern. Spiky, unpredictable reads want on-demand, not a guessed provisioned number.

## P6: Iceberg small-file explosion from streaming Firehose writes

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status:** ANTICIPATED, not yet hit; to be grounded in a real artifact once the build reaches it.

- **Symptom:** lakehouse query times degrade steadily over days; reproducible training pulls back to MSI get slower and slower.
- **Wrong first hypothesis:** the queries need better partition predicates.
- **Root cause:** Firehose lands many tiny objects, and without compaction Iceberg accumulates thousands of small files plus stale snapshots, so every scan opens enormous numbers of files.
- **Fix:** schedule Iceberg compaction (rewrite data files) and snapshot expiration, and tune Firehose buffering toward larger objects.
- **Lesson:** a streaming sink into a table format is a maintenance commitment. Compaction and snapshot expiry are not optional background chores; they are part of the design.

## P7: Budget action attaches deny but does not stop in-flight spend

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status:** ANTICIPATED, not yet hit; to be grounded in a real artifact once the build reaches it.

- **Symptom:** the $75 budget action fires and attaches the deny policy to the platform role, but spend continues for a while afterward.
- **Wrong first hypothesis:** the budget action did not actually fire; the guardrail is broken.
- **Root cause:** the deny policy only blocks NEW actions taken by the platform role; already-running resources (a running endpoint, an active stream) keep billing, and the budget evaluates on a delay. The guardrail worked exactly as designed; the mental model was wrong.
- **Fix:** pair the deny action with the teardown Lambda (`infra/lambda/teardown/`) so breach also stops or deletes the expensive running resources, and document the budget evaluation delay so the soft alerts ($5/$15/$25/$30) are the real early warning.
- **Lesson:** a deny policy prevents starting new spend; it does not stop spend already in flight. A hard cap needs an actuator (teardown), not just a gate.

## P8: Provider drift forces resource replacement

**Tags:** [PLATFORM / personal-build] TOOLING

**Status:** ANTICIPATED, not yet hit; to be grounded in a real artifact once the build reaches it.

- **Symptom:** an unrelated `terraform plan` proposes to destroy and recreate live resources after a routine `terraform init` upgraded a provider.
- **Wrong first hypothesis:** someone changed the resource configuration; find the offending edit.
- **Root cause:** the AWS provider auto-upgraded to a new minor with changed defaults or attribute handling, so the same config now diffs against existing state. No human changed the resource; the provider did.
- **Fix:** pin `aws ~> 5.x` plus `archive` and `random` in `infra/terraform/versions.tf`, commit a lockfile, and upgrade providers deliberately in their own reviewed change.
- **Lesson:** unpinned providers are an unreviewed dependency on someone else's release schedule. Pin them, lock them, and treat a provider bump as a real change. This story is why provider pinning is a hard requirement in Harbormaster.
