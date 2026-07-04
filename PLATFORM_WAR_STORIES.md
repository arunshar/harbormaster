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

## P9: Replication-slot bloat: a stalled CDC consumer pins WAL until the source disk fills

**Tags:** [PLATFORM / personal-build] CORRECTNESS TOOLING

**Status:** GROUNDED 2026-07-03 (Phase 2 drill, run live; transcript `docs/drills/P1_slot_bloat.md`). Master-plan catalog name: P1.

- **Symptom:** with the CDC consumer stalled (nothing draining the `harbormaster_cdc` pgoutput slot), source-side WAL retention grew without bound while ordinary writes continued: 0 -> 6,926,136 -> 23,703,352 -> 40,480,568 -> 57,257,784 -> 74,035,000 lag bytes across five write rounds on a live Postgres 16, ~74 MB pinned in minutes on a toy workload. On the real t4g.micro (20 GB gp3) this is a countdown to a full disk and a crashed database, and the database looks perfectly healthy the whole time.
- **Wrong first hypothesis:** disk growth on the Postgres source means table or index bloat, so tune autovacuum or add storage. Vacuum does nothing here; the growth is not in tables at all.
- **Root cause:** a logical replication slot is a contract: Postgres must retain every WAL segment past the slot's `confirmed_flush_lsn` until the consumer confirms it, no matter how long that takes. A stalled consumer (crash-looping task, wedged Kafka Connect, paused demo) never confirms, so WAL is pinned forever; `pg_replication_slots` shows the slot `active = false` with monotonically growing lag, which is exactly the signature the drill reproduced.
- **Fix:** three layers, all in the tree. (1) Visibility: `cdc/monitor/slot_lag.py` computes per-slot lag from `pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)` (fallback `restart_lsn`); the drill asserted `evaluate_lag_alert` fires at threshold (it did, at 65,536 bytes). (2) Alerting: `infra/terraform/modules/cdc_monitoring/main.tf` publishes `Harbormaster/CDC ReplicationSlotLagBytes` every minute from a VPC Lambda and alarms to the FinOps SNS topic, with `treat_missing_data = "breaching"` so a dead monitor also pages. (3) Prevention: `heartbeat.interval.ms=10000` in `cdc/connector/config.py` keeps an idle-but-healthy pipeline advancing the slot, so lag on the graph always means a real stall. Recovery is the consumer draining the slot: the drill's drain collapsed 74,035,000 bytes to 0 in one call. (The drill uses its own slot, hm_drill_p1_slot_bloat, and never touches the production slot.)
- **Lesson:** a replication slot is not a free bookmark; it is a standing lien on the source's disk held by the slowest consumer. Monitor the slot, not the consumer: consumer-side health checks miss zombie states, but `pg_replication_slots` lag cannot lie. And alarm on silence too, because the monitor that would tell you about the stall can itself be the thing that died.

## P10: Duplicate CDC events after a consumer restart: at-least-once delivery vs a non-idempotent sink

**Tags:** [PLATFORM / personal-build] CONCURRENCY CORRECTNESS

**Status:** GROUNDED 2026-07-03 (Phase 2 drill through the real applier; transcript `docs/drills/P2_duplicates.md`). Master-plan catalog name: P2. Echoes MSI lesson #24.

- **Symptom:** after a simulated consumer crash between sink-ack and offset commit, redelivery re-applied 5 already-applied events in the unguarded configuration (5 double-writes in the audit trail); after a simulated group-rebalance zombie redelivery, the unguarded sink let a stale event win: the watchlist row's severity regressed 0.95 -> 0.9 and the analyst's newer edit silently vanished, with the online item claiming lsn 2000 after lsn 3000 had already applied.
- **Wrong first hypothesis:** whole-row upserts are naturally idempotent, so at-least-once redelivery is harmless; in-order replay converges to the same state. The drill's schedule A shows exactly this: a full in-order replay through the unguarded sink happens to converge, which is precisely why this bug passes testing and ships. The convergence is an accident of the schedule, not a property of the sink.
- **Root cause:** at-least-once transport guarantees redelivery windows (crash before offset commit) and, after a rebalance, a zombie consumer can re-apply events its replacement already processed, out of order across the group generation. A last-write-wins upsert has no defense: whichever delivery arrives last becomes the truth, including a stale one.
- **Fix:** the LSN-guarded idempotent sink plus the commit protocol, both in the tree and both exercised by the drill through the real code path. Guard: every online item carries `last_applied_lsn` and every write is a whole-item conditional put, `attribute_not_exists(last_applied_lsn) OR last_applied_lsn < :lsn` (`cdc/sinks/dynamo.py`); deletes write a guarded soft-delete marker so replays cannot resurrect rows. Protocol: `cdc/consumer/applier.py` commits Kafka offsets only after every sink acks the batch. Under the guard, both drill schedules converged byte-identically to the exactly-once baseline (state sha `ca123c35...`), with the redeliveries visible in the audit trail as `applied=false` rows, transport truth and state truth kept separate on purpose.
- **Lesson:** exactly-once is not a transport setting you turn on; it is at-least-once transport plus an idempotent sink, and the idempotency key must encode ORDER (a monotonic LSN), not just identity (the primary key). Test the zombie schedule, not just the clean replay: the failure mode that matters arrives out of order.

## P11: Training-serving skew: the holdout gate cannot see a bug the offline export itself produced

**Tags:** [PLATFORM / personal-build] CORRECTNESS MLOPS

**Status:** GROUNDED 2026-07-04 (Phase 3 drill through the real gate and shadow-diff code; transcript `docs/drills/L1_training_serving_skew.md`). Master-plan catalog name: L1.

- **Symptom:** a candidate that standardizes a feature `(x - mean) / std` in its offline training-set export but receives the RAW, unstandardized value on the online serving path passes the holdout gate cleanly (AUC 1.0, calibration_ratio ~1.0) and only reveals the mismatch once shadow compares it against the champion on real live traffic: mean absolute score divergence 0.61 against a 0.05 threshold, a clear fail.
- **Wrong first hypothesis:** a holdout AUC of 1.0 and a calibration ratio of ~1.0 mean the candidate is safe to promote. Both metrics are computed entirely against the offline-encoded holdout set, so a bug that lives specifically in the offline/online encoding boundary is invisible to them by construction, no matter how clean the numbers look.
- **Root cause:** the holdout gate answers "is this model good at the task it was evaluated on," not "does the serving path actually feed it what it expects." Those are different questions whenever training and serving compute a feature independently (here: a standardization step present in one path and silently missing in the other), and echoes the real precip-standardization bug Arun hit and fixed in the PC-RF paper, a mean-subtraction choice that made `coarse_mass` negative on 10 of 16 samples, invisible until the actual physics projection ran.
- **Fix:** shadow (`mlops/shadow_diff.py`'s `score_diff`), run against real online-encoded traffic before any canary weight is set, exists precisely to catch this class of bug; the promotion state machine (`mlops/promote.py`) never lets a candidate reach canary without a clean shadow window, per invariant in `docs/phases/PHASE_3.md`.
- **Lesson:** an offline metric is only as trustworthy as the assumption that offline and online compute the same thing; that assumption is exactly what training-serving skew violates, and no amount of holdout rigor substitutes for testing the real serving path.

## P12: A candidate that passes every offline check regresses only once canary traffic actually reaches the failure mode

**Tags:** [PLATFORM / personal-build] MLOPS RELIABILITY

**Status:** GROUNDED 2026-07-04 (Phase 3 drill through the real promotion state machine; transcript `docs/drills/L2_canary_rollback.md`). Master-plan catalog name: L2.

- **Symptom:** a candidate with a clean holdout gate and a clean shadow window (the shadow sample never happened to include the input distribution that triggers the regression) advances cleanly through canary weight 5, then the SLO error budget starts burning at weight 25: `mlops/promote.py`'s `run_promotion` set weights `[5, 25]` and stopped, `revert_to_champion()` was called, and the transition sequence ends `canary_25: revert`, never advancing to 50 or 100.
- **Wrong first hypothesis:** if holdout and shadow both pass, the candidate is safe; canary is just a formality before full rollout. The drill's construction shows precisely why this is false: shadow only samples a fraction of live traffic, and a rare-but-real input distribution can pass through an entire shadow window by chance without ever being sampled, the same "convergence is an accident of the schedule" lesson from P10 applied to sampling instead of scheduling.
- **Root cause:** every pre-production check (holdout, shadow) is a finite sample of a distribution that production traffic explores more fully as canary weight increases; the checks are necessary but structurally cannot be sufficient, so canary at increasing, bounded weights is the layer that actually meets the full traffic distribution before a rollout is irreversible.
- **Fix:** the promotion saga's compensating action (DR-3, `docs/SYSTEM_DESIGN_DECISIONS.md`): a burn-rate breach at any canary weight triggers a full, immediate, one-step revert to the prior champion, never a partial rollback or a "wait and see." The drill proves this holds at every one of the four canary weights independently (`mlops/tests/test_promote.py`'s parametrized revert test), not just the one weight this specific drill exercises.
- **Lesson:** offline and shadow checks bound the *known* failure surface; canary at real, increasing traffic weights is what catches the *unknown* one, and the only way that safety net is trustworthy is if rollback is automatic, immediate, and exercised in CI, not a manual scramble invented at incident time.

## P13: PyFlink's Python UDF worker is not the driver's Python environment

**Tags:** [PLATFORM / personal-build] TOOLING CORRECTNESS

**Status:** GROUNDED 2026-07-04 (Phase 1 W1 live run, first-ever real KDA execution of the feature job; commit `fix(flink): resolve worker-side deps, TTL, and score-ais schema`).

- **Symptom:** `FeatureProcess` (a `KeyedProcessFunction`) failed with `ModuleNotFoundError: No module named 'flink'` even though `job.py`'s own top-level `from flink.transforms import ...` ran fine at driver startup, and later, after that was fixed, failed with `ModuleNotFoundError: No module named 'boto3'` from inside the SAME class's lazily-imported DynamoDB client, even though `boto3` is present and importable everywhere else in the container.
- **Wrong first hypothesis:** if the driver process can import a module, the job can use it anywhere, including inside a stateful operator's per-record callback. Two separate attempts to ship the local `flink`/`features` packages as an explicit dependency (`env.add_python_file()`, then the `pyFiles` Runtime Property with two comma-separated paths) both hit real, confirmed bugs in Managed Flink's own Python-dependency distributed-cache staging (a `FileAlreadyExistsException` reproduced twice, deterministically, with different cache hashes each time) before the actual root cause was even reached.
- **Root cause:** a stateful `KeyedProcessFunction` executes inside a separate Python UDF worker subprocess (Apache Beam's process-mode portability harness), which does not inherit the driver's `sys.path` or installed packages. cloudpickle only serializes a referenced function/class BY VALUE when it is defined in `__main__`; anything imported from a real package (`flink.transforms`, `features.features`) gets pickled BY REFERENCE, and the worker then needs that exact module importable on its OWN sys.path to unpickle it. Third-party packages have the identical problem: `boto3` sits in the driver's site-packages but not the worker's.
- **Fix:** inlined the two local packages' logic directly into `job.py` (a documented, deliberate duplicate of the tested source files, not an import), so the referenced code lives in `__main__` and serializes by value with no dependency-staging step at all. For the genuinely third-party `boto3`, used `env.set_python_requirements()` with a one-line `requirements.txt` (a single-file mechanism, distinct from and more reliable than `pyFiles`, and the one AWS's own separate `PythonDependencies` example is built around).
- **Lesson:** "it imports in the driver" is not evidence it will import in a stateful operator's worker. On Managed Flink specifically, don't reach for `pyFiles`/`add_python_file` for anything beyond a single well-tested dependency path; for local, tightly-coupled helper code, inlining into the entry-point module sidesteps the whole distributed-cache staging subsystem, which has real, hard-to-predict failure modes under multi-path use.

## P14: A replay fixture's historical timestamps make an online store's TTL fire on arrival

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status:** GROUNDED 2026-07-04 (Phase 1 W1 live run; same commit as P13).

- **Symptom:** the Flink job ran cleanly with zero errors and DynamoDB writes succeeded, but a table scan showed the item count fluctuating (7, 5, 7, 8, then permanently 0) across repeated checks seconds apart, and neither a known target record nor a fresh, manually-injected test record was ever observed to persist.
- **Wrong first hypothesis:** the Kinesis consumer must be stalled or missing records (spent real time ruling out stream-position timing, shard assignment, and a genuine consumer stall via `numRecordsIn`/CloudWatch metrics and direct `put-record` tests, before finding the real cause).
- **Root cause:** `feature_item()`'s DynamoDB `ttl` attribute is computed from the AIS fix's own event time, correct for genuinely live data. The replay fixture's timestamps are from June 2024; on this table, DynamoDB's TTL is enabled on that same `ttl` attribute, so every write was, from the instant it landed, already more than a year past its own expiry, and DynamoDB's TTL sweeper was deleting items within seconds, fast enough to make a stalled consumer the more plausible-looking explanation.
- **Fix:** override `ttl` with a wall-clock-based value (`time.time() + 7*86400`) at the DynamoDB write call site, leaving the shared, unit-tested `feature_item()` function unchanged (its formula is correct for real production event times; only the replay/demo path needed the override).
- **Lesson:** when a demo or backfill replays historical data through a live pipeline, every downstream system that derives an absolute deadline (TTL, cache expiry, retry backoff) from the payload's own timestamp needs a second look: the deadline math is correct, but the input assumption ("this timestamp is roughly now") silently breaks. A fluctuating-then-empty count is a distinctive enough signature to check TTL configuration before chasing consumer-side theories.

## P15: A precomputed-feature payload silently drifted from the real serving schema

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status:** GROUNDED 2026-07-04 (Phase 1 W1 live run; same commit as P13/P14).

- **Symptom:** with the Flink pipeline itself fully fixed and DynamoDB writes landing correctly, the HITL review queue stayed empty; the serving API's own access logs showed every `POST /v1/score-ais` call from Flink returning `422 Unprocessable Entity`, silently, because the scorer call was written as best-effort (`except URLError: pass`).
- **Wrong first hypothesis:** since `urllib.request.urlopen` never raised past that catch block in a way that surfaced anywhere, the natural read was "the pipeline works, HITL is just not receiving anything anomalous enough to flag" -- a plausible story right up until the serving logs were actually read.
- **Root cause:** `score_request()` built a flat payload with the vessel's own precomputed `WindowFeatures` embedded under a `"features"` key. The real, current `AisScoreIn` Pydantic schema in `serving/app/models.py` has never had a `features` field: it expects `{mmsi, fix, history}` and recomputes its own anomaly features server-side from the raw fix and history. The two components' contracts had drifted apart, and nothing enforced them staying in sync since they live in different subsystems with independent test suites.
- **Fix:** restructured `score_request()` to send `{mmsi, fix: {...}, history: [...]}`, passing Flink's own keyed previous-fix state as one-entry history so the scorer sees the same two points Flink used for its own cheap gate. Updated the function's own unit test to assert the real shape instead of the stale one.
- **Lesson:** a "best-effort" try/except around a cross-service call is exactly where schema drift hides longest, because the failure never surfaces as an exception anywhere a developer is likely to look; it just quietly starves whatever depends on that call succeeding. Read the actual receiving service's logs, not just the sender's, before concluding a downstream system "isn't flagging anything."

## P16: A deterministic planner silently skips a detector below its history threshold

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status:** GROUNDED 2026-07-04 (Phase 1 W1 live run; commit `fix(flink): retain a rolling history window so gap detection actually runs`).

- **Symptom:** with the score-ais schema fixed (P15) and 200 OK responses flowing, the HITL queue correctly received an `off_corridor` anomaly for one MMSI, but the fixture's documented gate-G8 known anomaly (MMSI 367000001, a 180-minute AIS silence gap) never appeared, always scoring `n_reasons=0`, even though it was reaching the scorer successfully.
- **Wrong first hypothesis:** the gap-detection agent's own severity/threshold tuning must not consider this specific gap severe enough to flag -- a plausible story, since P_phys for this gap is 1.0 (the reappearance position is easily reachable at normal speed, so nothing about the gap looks kinematically impossible on its own).
- **Root cause:** `serving/app/agents/heuristic_planner.py`'s `HeuristicPlanner` routes deterministically by history length: the abnormal-gap detector (`GapDetectorAgent`) is only added to the execution plan when `n_history >= 3`. Flink's keyed state tracked only the single most recent fix, so every `score-ais` call had exactly one history entry (`n_history=1`); the gap-detection node was never in the plan at all, so nothing about severity or threshold mattered -- the detector simply never ran for any record this pipeline produced. Confirmed by sending the exact payload Flink would send for the gap-crossing record directly to the endpoint with `curl`: with 5 history entries it correctly returned `abnormal_gap`, `hitl_required: true`.
- **Fix:** changed `FeatureProcess`'s keyed state from a single previous fix to a rolling window of the last 5 (still a plain JSON-encoded `ValueState`, no new state type), and `score_request()` to send the full retained history rather than one prior fix.
- **Lesson:** when a fusion/routing layer conditions on an input's *shape* (here, how much history it received) rather than just its *values*, a producer that only ever supplies the minimum shape can make an entire code path permanently dead without any single call ever failing or looking wrong in isolation. "It's scoring successfully" and "it's being evaluated for X" are different claims; verify the second one directly (a synthetic payload with a known-should-trigger shape) rather than inferring it from the first.
