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

**Status: ANTICIPATED (not yet observed in a live run)**; hypothetical, not tied to a real observed run, commit, log, or `file:line`; to be grounded in a real artifact once the build reaches it.

- **Symptom:** one Kinesis shard runs hot and throttles (`ProvisionedThroughputExceededException`) while sibling shards sit nearly idle; end-to-end feature latency spikes for a subset of vessels.
- **Wrong first hypothesis:** the stream is under-provisioned overall; add more shards.
- **Root cause:** the partition key is a coarse region code, so a few dense shipping lanes map all their traffic onto one shard. Total throughput is fine; the key distribution is skewed.
- **Fix:** repartition on a higher-cardinality key (MMSI-derived hash) so per-vessel traffic spreads evenly, and add a hot-key metric so skew is visible before it throttles.
- **Lesson:** shard count treats a symptom; partition-key cardinality is the disease. Always graph per-shard, not just aggregate, throughput.

## P2: Flink event-time windows never fire under late AIS

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status: ANTICIPATED (not yet observed in a live run)**; hypothetical, not tied to a real observed run, commit, log, or `file:line`; to be grounded in a real artifact once the build reaches it.

- **Symptom:** per-vessel feature windows in Flink stop emitting; the online feature store goes stale even though raw events keep arriving.
- **Wrong first hypothesis:** the Flink job is wedged or the sink is down; restart it.
- **Root cause:** watermarks stall because a handful of vessels emit far-future or far-past timestamps, dragging the watermark and preventing windows from closing. The job is healthy; the watermark strategy is wrong.
- **Fix:** add bounded-out-of-orderness with an idleness timeout, clamp obviously bogus timestamps at ingest, and route clamped records to a side output for inspection.
- **Lesson:** in event-time streaming, a stuck pipeline is usually a watermark problem, not a liveness problem. Guard the watermark against adversarial timestamps.

## P3: Debezium snapshot locks the RDS source during initial CDC

**Tags:** [PLATFORM / personal-build] CONCURRENCY

**Status: ANTICIPATED (not yet observed in a live run)**; hypothetical, not tied to a real observed run, commit, log, or `file:line`; to be grounded in a real artifact once the build reaches it.

- **Symptom:** when CDC is first enabled, queries against the operational RDS Postgres slow sharply and the connector takes a long time to reach streaming mode.
- **Wrong first hypothesis:** RDS is undersized; scale the instance up.
- **Root cause:** the default Debezium snapshot reads the whole table set before streaming, holding contention against live traffic; the bottleneck is the snapshot strategy, not instance size.
- **Fix:** switch to an incremental snapshot, confirm `wal_level=logical` and replica identity are set correctly, and schedule the initial snapshot for a low-traffic window.
- **Lesson:** CDC has a cold-start cost. Plan the snapshot like a migration, not a config toggle.

## P4: SageMaker async endpoint silently drops bursts

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status: ANTICIPATED (not yet observed in a live run)**; hypothetical, not tied to a real observed run, commit, log, or `file:line`; to be grounded in a real artifact once the build reaches it.

- **Symptom:** during traffic bursts, some Pi-DPM inference requests produce no result and no error surfaces to the caller.
- **Wrong first hypothesis:** the model container is crashing on certain inputs.
- **Root cause:** the async endpoint's internal queue overflows past its limit and silently sheds requests; without the failure-path SNS notification configured, the drops are invisible.
- **Fix:** wire the async endpoint's success and failure SNS topics, set autoscaling on the backlog-per-instance metric, and make the caller treat "no result within SLA" as an explicit retry, not a success.
- **Lesson:** async means a queue, and a queue means a drop policy. If you have not configured the failure notification, you are losing requests blind.

## P5: DynamoDB online store throttles on cold feature reads

**Tags:** [PLATFORM / personal-build] CONCURRENCY

**Status: ANTICIPATED (not yet observed in a live run)**; hypothetical, not tied to a real observed run, commit, log, or `file:line`; to be grounded in a real artifact once the build reaches it.

- **Symptom:** the GeoTrace front door sees elevated p99 latency and `ProvisionedThroughputExceeded` on first lookups for vessels not seen recently.
- **Wrong first hypothesis:** the table needs a fixed higher provisioned capacity.
- **Root cause:** bursty, spiky read patterns against a provisioned-capacity table; cold vessels arrive in clusters that exceed the steady provisioning.
- **Fix:** move the online store to on-demand capacity (or add autoscaling with a burst buffer), and add a short-TTL cache in the front door for hot vessels.
- **Lesson:** match capacity mode to access pattern. Spiky, unpredictable reads want on-demand, not a guessed provisioned number.

## P6: Iceberg small-file explosion from streaming Firehose writes

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status: ANTICIPATED (not yet observed in a live run)**; hypothetical, not tied to a real observed run, commit, log, or `file:line`; to be grounded in a real artifact once the build reaches it.

- **Symptom:** lakehouse query times degrade steadily over days; reproducible training pulls back to MSI get slower and slower.
- **Wrong first hypothesis:** the queries need better partition predicates.
- **Root cause:** Firehose lands many tiny objects, and without compaction Iceberg accumulates thousands of small files plus stale snapshots, so every scan opens enormous numbers of files.
- **Fix:** schedule Iceberg compaction (rewrite data files) and snapshot expiration, and tune Firehose buffering toward larger objects.
- **Lesson:** a streaming sink into a table format is a maintenance commitment. Compaction and snapshot expiry are not optional background chores; they are part of the design.

## P7: Budget action attaches deny but does not stop in-flight spend

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status: ANTICIPATED (not yet observed in a live run)**; hypothetical, not tied to a real observed run, commit, log, or `file:line`; to be grounded in a real artifact once the build reaches it.

- **Symptom:** the $75 budget action fires and attaches the deny policy to the platform role, but spend continues for a while afterward.
- **Wrong first hypothesis:** the budget action did not actually fire; the guardrail is broken.
- **Root cause:** the deny policy only blocks NEW actions taken by the platform role; already-running resources (a running endpoint, an active stream) keep billing, and the budget evaluates on a delay. The guardrail worked exactly as designed; the mental model was wrong.
- **Fix:** pair the deny action with the teardown Lambda (`infra/lambda/teardown/`) so breach also stops or deletes the expensive running resources, and document the budget evaluation delay so the soft alerts ($5/$15/$25/$30) are the real early warning.
- **Lesson:** a deny policy prevents starting new spend; it does not stop spend already in flight. A hard cap needs an actuator (teardown), not just a gate.

## P8: Provider drift forces resource replacement

**Tags:** [PLATFORM / personal-build] TOOLING

**Status: ANTICIPATED (not yet observed in a live run)**; hypothetical, not tied to a real observed run, commit, log, or `file:line`; to be grounded in a real artifact once the build reaches it.

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

## P17: The job's own IAM role never had permission to read its own code

**Tags:** [PLATFORM / personal-build] TOOLING

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 first live EMR run; commit `fix(lake): four real bugs from the first live EMR backfill run (W2)`).

- **Symptom:** the first-ever real `aws emr-serverless start-job-run` failed immediately at driver startup with `Exception in thread "main" java.io.FileNotFoundException: File s3://.../code/lake_backfill_job.py does not exist`, even though a direct `aws s3 ls` on that exact key confirmed the object existed.
- **Wrong first hypothesis:** the upload silently failed, or there's an S3 eventual-consistency lag between the `aws s3 cp` and the job start moments later.
- **Root cause:** `modules/emr_backfill`'s job-execution IAM policy granted `s3:GetObject`/`s3:ListBucket` on exactly two prefixes: the raw-extract input path and `<lake_bucket>/iceberg/*` (its output). Nobody had granted it read access to `<lake_bucket>/code/*`, where the entry point script, `--py-files` zip, and venv archive are uploaded (`scripts/package_lake_for_emr.sh --upload`). EMR Serverless's driver process uses the job's own execution role for every S3 call, including fetching its own entry point; IAM silently denies the read, and Spark's JVM-level error handling surfaces that as `FileNotFoundException`, not `AccessDenied`, which is what made the wrong hypothesis (upload failure) initially plausible.
- **Fix:** added a `ReadJobCode` IAM statement granting `s3:GetObject`/`s3:ListBucket` on `<lake_bucket>/code/*`.
- **Lesson:** a Terraform module's least-privilege IAM policy is written against the resources the AUTHOR anticipated the job would touch; a job's own code/dependency artifacts are easy to forget precisely because they feel like packaging plumbing, not "data." When Spark (or any JVM runtime backed by AWS SDKs) reports a resource "does not exist" for something you can directly confirm exists via the CLI, suspect a silently-denied read before suspecting the upload.

## P18: A dependency-free Python 3.10+ idiom breaks silently on the actual EMR runtime's Python 3.9

**Tags:** [PLATFORM / personal-build] TOOLING

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 first live EMR run; same commit as P17).

- **Symptom:** after fixing the IAM and schema/region issues (both caught by earlier attempts at this same live run), the job failed with `TypeError: zip() takes no keyword arguments` inside the corridor-graph derivation code, which had 40 passing local unit tests and had never shown this failure in any local run.
- **Wrong first hypothesis:** a packaging problem (stale `lake_pkg.zip`, wrong module resolving) since the code visibly worked locally moments earlier.
- **Root cause:** `zip()`'s `strict=` keyword argument was added in Python 3.10; the dev machine runs Python 3.12 (where the code was written and tested), but the actual EMR Serverless `emr-7.2.0` Spark image ships Python 3.9.21, confirmed directly (`docker run ... python3 --version`) rather than assumed. The project's own ruff configuration (`B905`) actively *requires* an explicit `strict=` on every `zip()` call, which is excellent practice for the Python 3.10+ dev environment and actively wrong for code that has to run on this specific, older, externally-fixed runtime.
- **Fix:** removed `strict=` from the three call sites (the paired sequences are provably equal length by construction: they're built from the same source array or the same grouped-by operation, so strictness was documentation, not a correctness lever), with `# noqa: B905` to keep the project-wide lint rule intact for every other file.
- **Lesson:** "runs on my Python" is not a substitute for checking the actual target runtime's version when a job ships to a managed service with its own fixed, vendor-controlled image (EMR Serverless, Lambda, Glue, etc.) -- the target's Python version is a real constraint on which language features are usable, independent of what the project's own lint config assumes or enforces elsewhere. Verify it directly (pull the real image, check the version) rather than assuming parity with the dev environment.

## P19: A pure function's own docstring predicted the bug the Spark wiring around it didn't account for

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 first live EMR run; commit `fix(lake): four real bugs from the first live EMR backfill run (W2)`).

- **Symptom:** the first live EMR job, past the IAM fix (P17), failed with `pyspark.errors.exceptions.base.PySparkTypeError: ... datetime64[ns, UTC] ... Expected a string or bytes dtype`, thrown from inside `mapInPandas`'s Arrow conversion of the gate/canonicalize step's output.
- **Wrong first hypothesis:** the fixture parquet itself has the wrong dtype for `t` (a real, separate issue that WAS also present and fixed first: the ad hoc fixture-to-parquet conversion let pandas auto-infer `t` as `datetime64`, when the raw-read schema declares it `StringType`). Fixing that alone did not clear the error, which is what surfaced this second, distinct bug.
- **Root cause:** `lake/backfill/job.py`'s `mapInPandas(..., schema=raw.schema)` reused the RAW input schema (`t: StringType`) as the declared OUTPUT schema for `_gate_and_canonicalize_partition`, whose actual return value is `canonicalize_positions(pdf)` -- and that function's own docstring says outright "t is coerced to ... a UTC timestamp." The function was correct and honest about its own contract; the Spark wiring around it just never read that contract when declaring the schema Arrow would enforce on the way back out.
- **Fix:** defined a separate `canonical_schema` (`t: TimestampType`) matching what `canonicalize_positions` actually returns, and passed that to `mapInPandas` instead of `raw.schema`.
- **Lesson:** when a Spark (or any typed-boundary) wrapper calls a pure, well-documented function and declares a schema for its output, the schema needs to describe THAT function's actual return shape, not the shape of whatever was fed into it. A docstring that already states the transformation ("coerced to X") is a specification the surrounding wiring should be checked against, not just prose.

## P20: A catalog client needs its own region even when every other AWS client in the process already has one

**Tags:** [PLATFORM / personal-build] TOOLING

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 first live EMR run; same commit as P19).

- **Symptom:** past the schema fix, the same job failed with `botocore.exceptions.NoRegionError: You must specify a region`, thrown from inside the Iceberg writer's Glue catalog client, on a job running inside `us-east-1` with `AWS_REGION` set on both driver and executors via `spark.emr-serverless.driverEnv`/`executorEnv`.
- **Wrong first hypothesis:** the Spark-level environment variables aren't actually propagating to the Python process, so the fix is to set them differently or in more places.
- **Root cause:** pyiceberg's `GlueCatalog` resolves its own boto3 client's region strictly from catalog properties (`glue.region`, falling back to the generic `client.region`), never from ambient process environment variables, EC2/ECS instance metadata, or another AWS SDK client already configured in the same process. `catalog_props` (`{"type": "glue", "warehouse": ...}`) never set either property, so the catalog client had no region source at all, regardless of what the surrounding Spark/EMR environment had.
- **Fix:** added `"glue.region"` and `"client.region"` (pyiceberg's actual property-key constant, confirmed by reading `pyiceberg/io/__init__.py`, not guessed) to `catalog_props`, both set from the same `AWS_REGION` env var already being threaded through for everything else.
- **Lesson:** a library's own catalog/client abstraction can have a narrower, catalog-specific configuration surface than "however AWS clients normally get their region." When a client raises a config error that "shouldn't happen because the region is set everywhere else," check whether THIS SPECIFIC client actually reads any of those sources, or only its own library-defined property keys.

## P21: A modern Docker build produces a manifest format SageMaker's own API rejects

**Tags:** [PLATFORM / personal-build] TOOLING

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 SageMaker demo-standin deploy; commit `fix(mlops): demo pi-dpm container needs an ENTRYPOINT for SageMaker's serve arg` and the preceding image-format fix).

- **Symptom:** `terraform apply`'s `aws_sagemaker_model` creation failed with `ValidationException: Unsupported manifest media type application/vnd.oci.image.index.v1+json`, for an image built and pushed with an ordinary `docker build` + `docker push` on current Docker Desktop.
- **Wrong first hypothesis:** `DOCKER_BUILDKIT=0` (the historical "use the legacy builder" escape hatch) would produce the older manifest format SageMaker expects. It did remove the multi-platform manifest-list wrapper (the literal `image.index` SageMaker's error named), but the resulting single-platform manifest was still OCI format (`application/vnd.oci.image.manifest.v1+json`), and a retried apply failed again with the same ValidationException, just naming the manifest instead of the index.
- **Root cause:** modern Docker Desktop's classic (non-BuildKit) builder has been effectively removed; `DOCKER_BUILDKIT=0` no longer changes the underlying builder or its default output format. BuildKit/buildx default to OCI media types for both the manifest list and the manifest itself. SageMaker's `CreateModel` API only accepts the older Docker Distribution v2 schema2 format (`application/vnd.docker.distribution.manifest.v2+json`), a real, still-enforced constraint that has nothing to do with the image's actual content.
- **Fix:** `docker buildx build --provenance=false --sbom=false --output type=image,name=<repo>:<tag>,push=true,oci-mediatypes=false` -- buildx's explicit output-config flag for forcing the legacy Docker manifest media type, verified before spending another Terraform apply cycle by pushing and immediately running `docker manifest inspect` to confirm `mediaType: application/vnd.docker.distribution.manifest.v2+json`.
- **Lesson:** "I built and pushed the image, so the registry has something valid" is not the same claim as "the specific consumer service accepts this image's manifest format." When a downstream AWS service's API rejects an image with a manifest-media-type error, verify the ACTUAL pushed manifest's `mediaType` directly (`docker manifest inspect`) before assuming a build-flag change worked; the old universal fix (`DOCKER_BUILDKIT=0`) can silently stop doing what it used to do as the underlying tooling evolves.

## P22: A container with no ENTRYPOINT can't answer the platform's own invocation convention

**Tags:** [PLATFORM / personal-build] TOOLING

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 SageMaker demo-standin deploy; commit `fix(mlops): demo pi-dpm container needs an ENTRYPOINT for SageMaker's serve arg`).

- **Symptom:** past the manifest-format fix (P21), the SageMaker endpoint create still failed, now with `CannotStartContainerError. Please ensure the model container for variant champion starts correctly when invoked with 'docker run <image> serve'`.
- **Wrong first hypothesis:** the container image itself is broken (bad base image, missing dependency, wrong platform) -- ruled out by the fact that the same image ran fine under a plain `docker run -p 8080:8080 <image>` with no trailing argument.
- **Root cause:** the Dockerfile had only a `CMD` (the gunicorn launch command), no `ENTRYPOINT`. Docker's own composition rule: when a container has no `ENTRYPOINT`, any arguments passed to `docker run <image> <args>` REPLACE `CMD` entirely rather than being appended to it. SageMaker's own real-time-inference contract is to invoke every container as `docker run <image> serve` (its convention for telling a container "this is the serving invocation," distinct from a training invocation); with no `ENTRYPOINT` to receive that argument, the container tried to execute a literal, nonexistent `serve` binary and exited immediately.
- **Fix:** added a one-line `entrypoint.sh` (`exec gunicorn --bind 0.0.0.0:8080 --workers 1 server:app`) as the image's `ENTRYPOINT`, which unconditionally launches the real server regardless of whatever argument SageMaker passes it (this container only ever serves, so there's no "training vs serving" branch to write). Verified locally before the next apply cycle: `docker run -v <real-model-dir>:/opt/ml/model <image> serve` (the exact invocation SageMaker uses) returned a healthy `/ping` 200.
- **Lesson:** a container that "runs fine" under a bare `docker run <image>` can still fail under the specific invocation convention its real deployment target uses. When a managed service documents "we invoke your container as `docker run <image> <mode-argument>`," test that exact command locally, argument included, before trusting a from-scratch Dockerfile that only ever had a `CMD`.

## P23: A shared git working directory means one terminal's branch switch is every terminal's branch switch

**Tags:** [PLATFORM / personal-build] TOOLING

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 SageMaker apply, caught before any real damage).

- **Symptom:** a `terraform plan` that had been clean minutes earlier suddenly proposed reverting an already-fixed, already-verified Cloud Map DNS record type back to the exact broken configuration from an earlier session (`SRV` -> `A`, the precise bug behind a much earlier serving-API outage), and wanted to destroy and recreate the live Managed Flink application.
- **Wrong first hypothesis (briefly considered, correctly rejected before acting):** the fix itself must have been lost or never actually committed.
- **Root cause:** two collaborators (a human, at a separate terminal, and an AI agent driving `git`/`terraform`/`docker` commands in the same tool-execution environment) were operating against the exact same on-disk git clone, not separate worktrees. A `git checkout` to an older branch run in one terminal changes HEAD for BOTH, silently, with no notification to the other. The other branch (`phase4-flywheel`) had genuinely branched off `phase3-lake` before the Cloud Map fix and before the entire day's live-debugging work existed, so every file on disk reverted to that earlier snapshot from the other party's perspective the moment the branch changed.
- **Fix:** `git branch --show-current` as a first move the instant something looked wrong (an unexpected diff appearing in an otherwise-clean plan), rather than assuming the file content was the ground truth; then an explicit `git checkout` back to the working branch, confirmed by re-running `git status`/`git branch --show-current` before touching Terraform again. No AWS resource was actually destroyed: the plan step (a review, not a mutation) is what surfaced the mismatch before an apply could act on it.
- **Lesson:** a shared, non-isolated working directory (as opposed to a git worktree per collaborator/session) means branch state is a piece of MUTABLE SHARED STATE, exactly like a live database -- any party can change it out from under any other party with no signal beyond "the files look different than expected now." When a plan/diff suddenly shows something that contradicts recent, verified work, check `git branch --show-current` before checking anything else; it is the cheapest, fastest way to rule out (or confirm) "we are no longer looking at the branch we think we are."

## P24: A promotion loop that moves fast enough to outrun the infrastructure it's driving

**Tags:** [PLATFORM / personal-build] TOOLING RELIABILITY

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 real promotion-pipeline run against the live SageMaker endpoint).

- **Symptom:** the real `mlops.promote.run_promotion` loop, wired to a real `boto3` `update_endpoint_weights_and_capacities` call for `set_canary_weight`, succeeded at canary weight 5 and then failed at canary weight 25 with `ClientError: ValidationException: Cannot update in-progress endpoint`.
- **Wrong first hypothesis:** the IAM role or the API call itself is malformed (both were confirmed correct: the exact same call had just succeeded once already).
- **Root cause:** `UpdateEndpointWeightsAndCapacities` is asynchronous; the endpoint transitions to `Updating` and stays there for real wall-clock time (tens of seconds, in this case) before returning to `InService`. `run_promotion`'s canary loop calls `set_canary_weight` for each weight in immediate succession with no gap, which is correct for a pure, synchronous, in-memory state machine (the function's own unit tests use fakes that return instantly) but not correct once `set_canary_weight` is wired to a genuinely asynchronous cloud API: the second call arrived while the first was still applying, and SageMaker rejects concurrent updates outright rather than queueing them.
- **Fix:** in the injected `set_canary_weight`/`revert_to_champion` callables (not in `run_promotion` itself, which stays a pure, fast, synchronous state machine matching its own tests), poll `describe_endpoint` for `EndpointStatus == "InService"` after issuing each weight update, before returning control to the loop.
- **Lesson:** a pure function's dependency-injection seam (callables passed in for the side-effecting steps) is exactly where the gap between "tested against fakes" and "wired to a real, asynchronous API" shows up, and it will not show up in the pure function's own test suite no matter how thorough, because those tests supply instantaneous fakes by construction. When wiring a real cloud client behind an interface designed around synchronous callables, the waiting/polling belongs in the adapter, not in a request to slow down or restructure the already-correct core logic.

## P25: An audit finding on paper vs. a live-verified fix are different claims, and the second one costs real money to skip

**Tags:** [PLATFORM / personal-build] CORRECTNESS TOOLING

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 SageMaker demo endpoint; fix applied and its effect confirmed live, not just planned).

- **Symptom:** none, observably -- which was the entire danger. A freshly-deployed SageMaker async endpoint (`initial_instance_count = 1`, `ml.g4dn.xlarge`, ~$0.74/hr) reported healthy, scored real invocations correctly, and gave no error, warning, or log line indicating anything was wrong with its autoscaling configuration.
- **Wrong first hypothesis (the one the original code silently encoded):** if `terraform apply` succeeds and the target-tracking policy and step-scaling policy both exist with no errors, scale-to-zero will eventually happen on its own.
- **Root cause:** the `customized_metric_specification` block for the target-tracking scale-in policy named only `metric_name`, `namespace`, and `statistic`, with no `dimensions` block. `ApproximateBacklogSizePerInstance` is published by SageMaker under the `EndpointName` dimension, and Application Auto Scaling's own rule is that a policy must specify the same dimensions its target metric was published with, or the policy queries a metric series that simply does not exist. A dimensionless spec means the alarms backing the policy sit in `INSUFFICIENT_DATA` forever: not "slow to react," but structurally unable to ever fire, meaning scale-in to zero would never happen, ever, on this configuration, regardless of how long the endpoint sat idle.
- **Fix:** added `dimensions { name = "EndpointName", value = aws_sagemaker_endpoint.pidpm.name }` inside the `customized_metric_specification` block -- a change caught by a prior, independent line-by-line audit against AWS's own canonical example notebook and API reference docs (not discovered by hitting the failure live), applied via a clean, single-resource `terraform apply` before real invocation traffic accumulated meaningful idle cost, and then verified by directly reading the two `TargetTracking-...` CloudWatch alarms' state after the fix (fresh alarms accumulating real data points, not still permanently `INSUFFICIENT_DATA` by construction).
- **Lesson:** "the resource exists and nothing errored" is a categorically different, weaker claim than "the mechanism this resource exists to provide actually functions," and the gap between the two is invisible by design for an alarm silently stuck in `INSUFFICIENT_DATA` -- there is no exception to catch, no log line to grep, nothing red anywhere, right up until the monthly bill. An external, independent line-by-line audit against the provider's own docs and reference examples caught a fix-before-demo-severity, real-dollar bug that a purely internal "did the apply succeed" check would never have surfaced; treat an audit's fix-before-demo findings as blocking, not advisory, precisely because the failure mode they catch is the kind that never announces itself.

## P26: The same class of bug survives a targeted audit fix, one alarm over

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status:** GROUNDED 2026-07-04 (Phase 3 W2 live scale-out-from-zero verification, found and fixed live in the same window as P25's applied fix).

- **Symptom:** immediately after P25's scale-IN fix was confirmed working (the endpoint genuinely reached 0 instances), a real invocation was sent to deliberately wake it from zero. `ApproximateBacklogSize` correctly showed a persistent 1.0 for 15+ minutes, but the endpoint's `DesiredInstanceCount` never moved off 0, and the `HasBacklogWithoutCapacity` CloudWatch alarm (whose whole job is to detect exactly this "backlog with zero capacity" condition and trigger the scale-out-from-zero step policy) sat with `StateReason: no datapoints were received` the entire time.
- **Wrong first hypothesis (briefly entertained before checking):** this metric simply has a longer natural publish latency than `ApproximateBacklogSize`, so more patience will resolve it.
- **Root cause:** the `has_backlog_without_capacity` alarm's Terraform declared `dimensions = { EndpointName = ..., VariantName = ... }`, but a direct comparison against AWS's own canonical scale-from-zero example (`docs.aws.amazon.com/sagemaker/latest/dg/async-inference-autoscale.html`) showed its `put_metric_alarm` call for this exact metric specifies `EndpointName` only. Confirmed empirically, not just by reading docs: querying CloudWatch's `get-metric-statistics` for `HasBacklogWithoutCapacity` with `EndpointName` alone returned real, non-empty datapoints (value 1.0, correctly reflecting the actual backlog-without-capacity condition) at the exact same moments the two-dimension query returned nothing. SageMaker does not publish `HasBacklogWithoutCapacity` under a `VariantName` dimension (unlike `ApproximateBacklogSizePerInstance`, which the earlier P25 fix correctly does key on `EndpointName`); the extra dimension here queried a series that has never existed, identical in shape to P25's bug but with an added dimension instead of a missing one.
- **Fix:** removed the `VariantName` dimension from the alarm, matching AWS's canonical pattern exactly. Verified live within the same session, not just planned: after the apply, the alarm immediately transitioned to `ALARM`, `DesiredInstanceCount` moved to 1, and the endpoint reached `InService` about 30 seconds later -- the full round trip from a genuinely zero-instance endpoint back to serving, observed end to end.
- **Lesson:** a prior audit fixing one instance of a bug class (a dimension mismatch on one metric spec) does not mean every other spec using dimensions is safe; each metric AWS publishes has its own specific, and not always intuitive, set of dimensions, and "this other alarm looks like it should follow the same pattern as the one that just got fixed" is exactly the reasoning that adds an extra dimension by analogy rather than by checking the actual canonical source per metric. When a metric silently never receives data, treat "wrong dimension set" as a first-class hypothesis and verify it by querying CloudWatch directly with different dimension combinations rather than assuming the config must be right because it resembles a known-good one.
## P27: Cross-validating two drift proxies stops a false concept-drift retrain the first proxy alone would have triggered

**Tags:** [PLATFORM / personal-build] ML-RELIABILITY

**Status:** GROUNDED 2026-07-04 (Phase 4 drill through the real drift/calibration/concept-proxy/decision-table code; transcript `docs/drills/L3_drift_classification.md`). Master-plan catalog name: L3. Renumbered from P13 (its number on branch `phase4-flywheel` before rebase) to P27 to resolve a numbering collision with `phase3-lake`'s own P13-P26, per `docs/WRITEUP_PLAN.md`'s already-diagnosed reconciliation note.

- **Symptom:** a volume of traces near the HITL routing threshold with high Pi-DPM epistemic variance (proxy 1, `mlops/concept_proxy.py`'s `flag_uncertain_trace`) fires on every single synthetic trace in the drill's batch, exactly the volume a naive "proxy 1 alone triggers retraining" design would read as concept drift. But the same batch's HITL disagreement rate (proxy 2, `disagreement_rate`) stays at 0.0: every operator who reviewed one of these traces confirmed the model's verdict was correct. `mlops/drift_decision.py`'s `classify_drift` correctly returns `category != "concept_drift"` on this exact combination.
- **Wrong first hypothesis:** a rising volume of near-threshold, high-uncertainty traces IS concept drift, and should trigger the DPO/GRPO preference pipeline. This conflates "the model is encountering more ambiguous cases" with "the model is now wrong about cases it used to get right"; proxy 1 alone cannot distinguish those two, since it never touches a ground-truth-adjacent signal at all.
- **Root cause:** there is no direct concept-drift detector in production anomaly detection (no ground-truth label stream), so proxy 1 is a population-shape signal, not a correctness signal; only proxy 2 (the rate at which real human operators override the model) is ground-truth-adjacent, if lagging. Treating a population-shape signal as sufficient on its own would trigger retraining on nothing more than "the model is seeing harder cases it is still right about," a false alarm the docs/phases/PHASE_4_SKETCH.md's decision table exists specifically to prevent.
- **Fix:** `classify_drift`'s precedence rule: a rising proxy 2 (disagreement) is concept drift regardless of proxy 1; a rising proxy 1 alone, with proxy 2 flat, routes only to `log_only`. The drill's fourth scenario constructs exactly the false-alarm combination (proxy 1 fires on 20/20 traces, proxy 2 at 0.0 across 20 labeled rows) and asserts the decision is NOT `concept_drift`.
- **Lesson:** a single proxy signal, however real, is not a substitute for a ground-truth-adjacent one when the two answer different questions; cross-validating a fast, noisy proxy against a slow, trustworthy one before acting is what turns "more traffic through the review queue" into information instead of a false-alarm retraining trigger.

## P28: The reward-hacking probe blocks a gamed checkpoint before it ever reaches shadow

**Tags:** [PLATFORM / personal-build] RL-SAFETY MLOPS

**Status:** GROUNDED 2026-07-04 (Phase 4 drill through the real probe and promotion state machine; transcript `docs/drills/L4_reward_hacking_probe.md`). Master-plan catalog name: L4. Renumbered from P14 (its number on branch `phase4-flywheel` before rebase) to P28, same collision-resolution as P27 above.

- **Symptom:** a synthetic DPO/GRPO-style candidate raises mean total reward from 5.0 to 8.0 over baseline, entirely by inflating the `soft`/`data`/`pref` reward terms while its `hard` term goes negative (a real kinematic-constraint violation) on 70% of the batch, versus 0% for baseline. `mlops.reward_hacking_probe.run_reward_hacking_probe` returns `blocked=True`, and `mlops.promote.run_promotion` halts at a new `reward_probe` step immediately after the holdout gate, never touching shadow or canary (`weights_set` stays empty).
- **Wrong first hypothesis:** a higher mean reward means a better candidate; reward alone is a sufficient promotion signal once the ordinary holdout gate has already passed. This is exactly backwards for an RL-fine-tuned candidate: pi-grpo's `RewardWeights` gives `hard` an unbounded, 5.0x-weighted term specifically so a real violation cannot be masked by three other terms combined, so a candidate that manages a higher *total* despite more violations is not improving, it is exploiting the softer terms.
- **Root cause:** the holdout gate and the reward-hacking probe answer different questions (as with P11's training-serving skew): the gate checks predictive quality on a fixed offline set, the probe checks whether a reward increase came with or without more physics violations. Neither substitutes for the other, which is exactly why the probe is a new, additional step, not a replacement for the gate.
- **Fix:** the probe's blocking condition, checked verbatim (as of gate 4.7's drill): `candidate_mean_reward > baseline_mean_reward AND candidate_hard_violation_rate > baseline_hard_violation_rate`. The drill's second scenario (an honest candidate: same reward increase, violation rate flat at 0.0) proves the probe does not simply penalize reward increases; it passes cleanly and the candidate promotes through the full state machine (`weights_set == [5, 25, 50, 100]`).
- **Lesson:** an unbounded, heavily-weighted penalty term in a reward function is only a real safeguard if something downstream actually audits whether a reward increase came at that term's expense; `hard_violation_in_either_arm` (`mlops/preference_builder.py`) exists precisely so this audit has the data it needs on every preference triple, not just the ones a human happens to inspect.
- **Follow-up (2026-07-04, later the same day):** a subsequent adversarial review found the rate-only condition above is magnitude-blind to a "boundary-riding soft-term hacker" (rides the violation-count threshold exactly while smuggling far-more-severe violations at a matched count); the blocking condition was hardened to `mean_up and (rate_up or candidate_mean_hard < baseline_mean_hard)`, signed off by Arun, see `docs/phases/PHASE_4.md`'s adversarial review addendum. This drill's own two scenarios (uniform hard shift) are unaffected by the hardening; both still produce the same verdicts.

## P29: A checkov baseline regenerated before the code it was supposed to gate

**Tags:** [PLATFORM / personal-build] TOOLING CORRECTNESS

**Status: GROUNDED**; 2026-07-06, branch feat/ab-masterclass-audit (commit 45d221c, `infra/terraform/.checkov.baseline` and the WAF/APIGW modules).

- **Symptom:** the Phase 2B checkov baseline was refreshed early in the change, then more IaC (the gated WAF, the API Gateway access-logging and authorizer work) landed after it. CI, running checkov against a baseline captured before that later code, would have suppressed the 4 new findings the new code introduced, reporting a clean scan while the ratchet was silently pointed at a stale snapshot.
- **Wrong first hypothesis:** no contemporaneous first-hypothesis note survives. The unsafe assumption encoded by the recorded sequence was that a baseline refreshed before the IaC was final would continue to expose findings introduced later.
- **Root cause:** a suppression baseline is a point-in-time diff against the tree, not a live policy. Capturing it before the final security code means every finding that code adds falls inside the "already known, already accepted" set by construction, so the gate cannot see the very findings it exists to catch.
- **Fix:** did not baseline the new findings. Fixed them in code instead: added the Log4j `KnownBadInputs` AWS Managed Rule and access logging to the WAF, so the findings resolve rather than get suppressed. Only the genuinely-accepted brownfield class (14-day log retention) was re-baselined, and the ratchet was re-run against the final tree to prove it still bites on anything new.
- **Lesson:** a suppression baseline is a liability unless it is regenerated with the code it gates, in the same change, as the last step. Prove the ratchet still fails on a fresh finding before trusting a green scan; a baseline captured too early turns the gate into a rubber stamp.

## P30: pyiceberg partition transforms silently need the pyiceberg_core Rust extension on the write path

**Tags:** [PLATFORM / personal-build] TOOLING CORRECTNESS

**Status: GROUNDED**; 2026-07-06, branch feat/ab-masterclass-audit (commit `69b8d1a`, `lake/iceberg.py`; local write-path failure and fallback, not a live cloud-lake run).

- **Symptom:** wiring day/bucket partition transforms into the Iceberg writer raised `NotInstalledError` locally on the write path, even though the transform objects constructed fine and the partition-spec API surface looked complete.
- **Wrong first hypothesis (implementation assumption exposed by the local write):** because the transforms could be declared and the partition-spec objects constructed, the environment appeared to have everything needed to apply them during a write.
- **Root cause:** pyiceberg's `day()` and `bucket()` partition transforms are implemented in the native `pyiceberg_core` Rust extension, which is not installed in the local environment. The Python API lets you declare the spec regardless; the extension is only required when a write actually has to apply the transform to real data, so the gap is invisible until the write executes.
- **Fix:** made the writer degrade honestly: it falls back to an identity partition when the extension is absent and applies the full day+bucket spec when the extension is present, rather than pretending the transform ran. The behavior is keyed on what the environment can actually do, not on the API being callable.
- **Lesson:** verify a library feature on the actual write path in the actual environment, not just against the API surface. A constructor that succeeds is not evidence the operation it configures can execute; native-extension-backed features fail at use time, not at declaration time.

## P31: Extracting inlined Flink UDFs to a module changes distributed serialization semantics

**Tags:** [PLATFORM / personal-build] CONCURRENCY CORRECTNESS

**Status: GROUNDED DESIGN-TIME CATCH (not a live worker failure)**; 2026-07-06, branch feat/ab-masterclass-audit (commit `5cb5a01`, `streaming/flink/window_logic.py` and `streaming/flink/job.py`).

- **Symptom:** pulling the inlined streaming window functions out into a testable `window_logic.py` module is a pure test-importability refactor with no behavior change on its face, but a naive extraction would have quietly altered how those functions ship to Flink workers.
- **Wrong first hypothesis (design assumption caught before a worker failure):** moving a pure helper from `__main__` into an importable module is a behavior-neutral testability refactor.
- **Root cause:** cloudpickle serializes a function defined in `__main__` (an inlined UDF) BY VALUE, shipping its actual bytecode; a function imported from a real package ships BY REFERENCE, a 53-byte pointer the worker must re-import on its own sys.path. Moving the functions to a module flips them from by-value to by-reference, exactly the P13 failure mode from the other direction: the worker would need `window_logic` importable on its own path, which the extraction does not guarantee.
- **Fix:** called `cloudpickle.register_pickle_by_value` on the extracted module so its functions still ship by value after the move, preserving the original job behavior while gaining a directly-importable, unit-testable module.
- **Lesson:** a refactor that only moves code to make it importable can still change distributed serialization semantics. In a cloudpickle/Flink pipeline, "where a function is defined" is a behavioral property, not just an organizational one; test the serialization boundary, not only the local import.

## P32: An IAM permissions-boundary on the deploy identity is a two-sided contract every managed role must honor

**Tags:** [PLATFORM / personal-build] TOOLING

**Status: GROUNDED DESIGN-TIME CATCH (not a failed apply)**; 2026-07-06 to 2026-07-07, branch feat/ab-masterclass-audit (commit `45d221c`, the deploy-identity boundary contract, and commit `5d11d42`, boundary wiring across all 12 role-creating modules and 19 roles). The boundary and module-role attachments were later applied live in the W3 window; Part C, deploying through the boundary-gated `harbormaster-platform` role, has not run.

- **Symptom:** adding a permissions-boundary condition to the deploy identity to close the `iam:*`-on-`Resource:*` privilege-escalation path is a change to one principal, but it silently creates an apply-time obligation: every `aws_iam_role` the deploy identity creates must now set `permissions_boundary`, or `CreateRole` is denied at apply.
- **Wrong first hypothesis (design assumption caught before apply):** tightening the deploy identity is a local policy edit; the roles it creates do not need a corresponding boundary change.
- **Root cause:** a permissions boundary that requires the principal to attach a boundary to any role it creates is a two-sided contract. Closing the escalation on the deploy identity is one side; the other side is that every module-defined role becomes non-creatable until it also carries the boundary. The escalation fix and the role-wide obligation are the same condition viewed from the principal versus the resource.
- **Fix:** threaded `permissions_boundary` through every module `aws_iam_role` the deploy identity manages, so the roles satisfy the boundary condition the principal now enforces, rather than discovering the denial one failed apply at a time.
- **Lesson:** a permissions boundary is not a local edit to one identity; it is a contract on the whole set of roles that identity manages. Closing an escalation on the principal creates an apply-time requirement on every downstream role, and both sides must land in the same change or the apply breaks.

## P33: Mutation testing as the anti-tautology check on new guards

**Tags:** [PLATFORM / personal-build] CORRECTNESS

**Status: GROUNDED TEST EVIDENCE**; 2026-07-03 to 2026-07-06, branch feat/ab-masterclass-audit (commit `64ac396`, the CDC sink LSN guard and equal-LSN regression, and commit `69b8d1a`, `serving/app/burn_rate.py` and its boundary tests). The temporary mutations were reverted; their historical red-run results are recorded here and were not rerun by this archive update.

- **Symptom:** the new CDC-sink and burn-rate tests all passed on the first run, which is exactly when a new test is least trustworthy: a green assertion proves nothing until a deliberate regression proves it can go red.
- **Wrong first hypothesis (explicitly challenged before shipping, not a production failure):** first-run green tests were enough to show that both new guards were covered.
- **Root cause:** a passing new test can be a tautology, asserting something the code makes true regardless of the logic under test. Without a mutation, "the test passes" and "the test binds the behavior" are indistinguishable, so a guard could ship with tests that never actually exercise its boundary.
- **Fix:** ran targeted mutations. Weakening the CDC duplicate guard from strict `<` to `<=` (admitting an equal-LSN redelivery) made the equal-LSN duplicate test fail as intended. Sabotaging the burn-rate calculator to always return `False` failed 5 tests. Both deliberate regressions turned the suite red, proving the new tests bind the real behavior, then both mutations were reverted.
- **Lesson:** a passing new test is not evidence of coverage until a deliberate regression makes it fail. Mutation testing is the cheap anti-tautology check: change the logic to be wrong on purpose and confirm the suite notices, especially for boundary guards where `<` versus `<=` is the whole point.

## P34: A checkov baseline silently coupled to a gitignored tfvars that CI cannot reproduce

**Tags:** [PLATFORM / personal-build] CI

**Status: GROUNDED**; 2026-07-07, branch feat/ab-masterclass-audit (commits 1943db9 and 9a75eab, the first PR CI run).

- **Symptom:** the new `iac-ci` checkov gate failed on the PR with about 24 findings reported as "new" across modules the branch never touched (`rds`, `ecs_*`, `sagemaker_pidpm`, `apigw`), while the identical `checkov -d infra/terraform --baseline infra/terraform/.checkov.baseline` command exited 0 on my laptop. Separately, `serving-ci` failed with `ModuleNotFoundError: No module named 'pyiceberg'` on 7 lake tests that were green locally.
- **Wrong first hypothesis (preserved by the two-commit debugging sequence):** the action's newer checkov version was the entire mismatch, so pinning checkov 3.3.6 would make CI agree with local. Commit `1943db9` applied that fix; commit `9a75eab` records why findings still persisted.
- **Root cause:** two independent local-versus-CI environment mismatches, not real regressions. First, the `bridgecrewio/checkov-action` bundled a newer checkov than the local 3.3.6 that generated the committed baseline, and a newer checkov adds and renames checks, so accepted brownfield findings resurfaced as "new." Pinning the version helped but findings persisted, because of the deeper cause: the baseline stored resource addresses with module count-indices (`module.apigw[0].aws_cloudwatch_log_group.access[0]`), but CI emitted non-indexed addresses (`module.apigw.aws_cloudwatch_log_group.access[0]`). checkov resolves a module `count` from variable values, and the baseline had been generated with `envs/base/terraform.tfvars` present, which is gitignored and sets `enable_phase1 = true`. CI checks out only tracked files, has no tfvars, and therefore cannot reproduce the indexed keys. Same checkov version, same tree, different finding keys, because the baseline was coupled to a gitignored file's variable resolution. (Sibling cause of the pyiceberg failure: the `[lake]` extra that CI installs declared only `pyarrow`, a leftover from when the lake tests were schema-shape only, before the Phase 2A tests exercised a real catalog.)
- **Fix:** pinned checkov to the baseline-generating 3.3.6 via a `pip install checkov==3.3.6` step, since `checkov_version` is not an input on that action (verified against its `action.yml`). Then reproduced CI exactly with `git archive HEAD infra/terraform | tar -x` (tracked files only, no tfvars, no `.terraform`) and regenerated the baseline against that CI-view tree, so its keys match what CI produces. Verified checkov 3.3.6 against the CI-view tree exits 0, the same accepted brownfield set is preserved (46 findings), and nothing the branch fixed (route auth, access logging) or any WAF/critical finding is hidden. Added `pyiceberg[sql-sqlite]>=0.7` to the `[lake]` extra. Documented the tfvars gotcha in the workflow so a future regeneration does not reintroduce it.
- **Lesson:** a suppression baseline (checkov, tflint, semgrep) is only as reproducible as the environment that generated it. Generate it the way CI sees the code: from the tracked tree with no gitignored tfvars and no local `.terraform` init state, and pin the scanner version, because the baseline is coupled to both. When a scan is green locally but red in CI on files the change never touched, suspect environment drift (tool version, resolved variables, init caches) before hunting a real regression.

---

## P35: A single tenant's population shift disappears into a global drift average

**Tags:** [PLATFORM / personal-build] CORRECTNESS OBSERVABILITY

**Status: GROUNDED**; 2026-07-11, branch phase5-multitenant (gate 5.9, drill M-drift-hidden; transcript `docs/drills/M_drift_hidden.md`, `make drill-m-drift-hidden`). Realizes the anticipated Phase-5 incident PHASE_5.md labels "P4".

- **Symptom:** the input-drift monitor stays green while one tenant's feature distribution has clearly moved; that tenant's model silently degrades with no alert.
- **Wrong first hypothesis:** the PSI/KS thresholds are too lax; lower the alert bar so the shift trips it.
- **Root cause:** the monitor pooled every tenant's rows into one distribution before computing PSI. A single tenant's genuine shift (drill fixture: PSI 9.51 on `tenant_a`) is diluted by nine stable tenants to a pooled PSI of 0.044, an order of magnitude below the 0.25 alert bar. Lowering the global bar would only trade the missed alert for a flood of false positives on the stable majority; the bar is not the problem, the pooling is.
- **Fix:** `mlops/tenant_drift.py` partitions the windows by `tenant_id` and runs the unchanged gate 4.1 `check_input_drift` once per tenant, so the shift shows up in that tenant's own result (`drifted_tenants(...) == ["tenant_a"]`) instead of being averaged away. The drill computes the pooled baseline from the same fixture, so the contrast is measured, not asserted.
- **Lesson:** an aggregate metric over a partitioned population hides per-partition regressions by construction, and tightening the aggregate's threshold cannot recover them without drowning in false alarms. Monitor at the granularity you make decisions at (here, per tenant), and prove the "a global monitor would have missed this" claim by computing the global monitor on the same data rather than assuming it.

---

## P36: Tenant isolation enforced in application code is one missing WHERE from a cross-tenant leak

**Tags:** [PLATFORM / personal-build] SECURITY CORRECTNESS

**Status: GROUNDED**; 2026-07-11, branch phase5-multitenant (gate 5.9, drill M-tenant-leak against a real Postgres; transcript `docs/drills/M_tenant_leak.md`, `make drill-m-tenant-leak`). Realizes the anticipated Phase-5 incident PHASE_5.md labels "P6"; echoes the MSI fail-open lesson.

- **Symptom:** a multi-tenant query path is one forgotten `AND tenant_id = :tid` away from returning another tenant's rows, and no test reliably catches the omission because the happy path looks identical.
- **Wrong first hypothesis:** a careful code review plus a repository-layer helper that always appends the tenant predicate is enough; isolation is an application-layer discipline.
- **Root cause:** application-layer isolation fails OPEN. Any code path that bypasses the helper (a raw query, a new endpoint, an ORM escape hatch) silently returns cross-tenant data, and the default behavior of a missing predicate is "return everything," the worst possible default for a security control.
- **Fix:** push isolation into Postgres Row-Level Security (`cdc/schema/tenancy.py`): every tenant table is `ENABLE` + `FORCE ROW LEVEL SECURITY` with a policy `USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)`. The `NULLIF(..., true)` makes an unset GUC match NO row, so isolation fails CLOSED. The drill proves it on a real database as a NOSUPERUSER owner: tenant B reads zero of tenant A's rows, a session with no `app.tenant_id` reads zero rows from all four tables, and a no-tenant write is rejected by the policy's `WITH CHECK` (SQLSTATE 42501).
- **Lesson:** a security control whose failure mode is "leak" belongs at the layer that cannot be bypassed. RLS makes cross-tenant isolation a property of the database, not a property of every query author remembering a predicate, and its fail-closed default (unset context matches nothing) is what turns "forgot the WHERE" from a breach into an empty result set. Test it as a non-superuser: superusers bypass RLS by design, so asserting from the bootstrap role is vacuous.

---

## P37: A rarely-hit tenant pays the full scale-from-zero cold start on its first request

**Tags:** [PLATFORM / personal-build] SERVING/SLO

**Status: ANTICIPATED (not yet observed in a live run)**; hypothetical, not tied to a real observed run, commit, log, or `file:line`; to be grounded in a real artifact once the W4 EKS/KEDA window measures the cold start. Realizes the anticipated Phase-5 incident PHASE_5.md labels "P7".

- **Symptom:** a tenant whose traffic is sparse enough that KEDA has scaled its serving deployment to zero incurs the full EKS pod cold-start latency on the next request, which may breach that tenant's SLO tier depending on the measured number.
- **Wrong first hypothesis:** scale-to-zero is free money; every idle tenant should scale to zero with no downside.
- **Root cause:** scale-to-zero trades standing cost for tail latency. The `0 -> 1` scale-out (image pull, container start, model load, health-check pass) lands entirely on the first request, and a real-time-tier tenant's p95 SLO may not tolerate it even though a batch-tier tenant's would.
- **Fix (anticipated):** measure the cold start in the W4 window (drill M3 / gate 5.3); if it breaches the real-time tier, keep `minReplicaCount: 1` for real-time tenants and reserve scale-to-zero for near-real-time/batch tiers, trading a few dollars of standing cost for the tail-latency SLO. Until measured, this stays a prediction, not a claim.
- **Lesson:** scale-to-zero is an SLO decision, not just a cost decision, and the right minimum-replica count is per-tier, not global. Do not assert the breach or the fix before the live measurement exists; the tier that can absorb a cold start is the one that should scale to zero.

---

## P38: A permissions boundary that omits a service silently disables its teardown

**Tags:** [PLATFORM / personal-build] TOOLING SECURITY

**Status: GROUNDED**; 2026-07-11, branch wave3-pressure-test (Wave 3 pressure-test finding; fix + regression test `tests/e2e/test_permissions_boundary.py`, `infra/aws/harbormaster-permissions-boundary.json`).

- **Symptom:** the structural EKS teardown guard (gate 5.0) and the nightly finops sweeper are built, tested, and wired, yet a review found that once the customer-managed permissions boundary is applied, they would never actually tear anything down.
- **Wrong first hypothesis:** the teardown Lambdas' inline IAM policies grant `eks:DeleteCluster` / `kafka:DeleteCluster`, so the delete path is covered.
- **Root cause:** effective permissions are the role's inline policy INTERSECT the permissions boundary. The boundary's Allow ceiling was authored in Phase 2B, before EKS and the guard existed, and was never widened when Phase 5 added them, so it omitted `eks:*`, `kafka:*`, and `autoscaling:*`. Every delete call is therefore AccessDenied at runtime; the Lambda catches it, decides "nothing to tear down", and publishes a healthy-looking SNS summary while the ~$73/mo EKS control plane and ~$18/day MSK Serverless bill indefinitely past the $75 hard cap. A structural guard defeated by a stale ceiling is exactly the procedural-failure mode it was built to replace.
- **Fix:** added `eks:*`, `kafka:*`, and `autoscaling:*` to the boundary ceiling, and a regression test that fails if any service the teardown Lambdas call is missing from the ceiling. The IAM-escalation Deny statements are unchanged.
- **Lesson:** a deny-by-omission ceiling is a second, invisible policy on every role, and it must be updated in lockstep with every new service the platform can stand up, or the cost safety-net for that service silently fails closed. Test the intersection, not just the inline grant: assert that every service a teardown path deletes is inside the boundary.

---

## P39: Row-level security over single-column business keys is not multi-tenant isolation

**Tags:** [PLATFORM / personal-build] SECURITY CORRECTNESS

**Status: GROUNDED (defect reproduced locally; composite-key fix implemented and verified locally)**; 2026-07-11 to 2026-07-13, Wave 3 finding plus P39 hardening (reproduced and regression-tested against local PostgreSQL 16; local kind CDC and production-image evidence in `docs/drills/P39_local_cdc_smoke.md` and `docs/drills/P39_test_suite.md`). The live AWS migration and derived-store rebuild have not run.

- **Symptom:** the RLS drills pass (a no-tenant session reads zero rows, tenant B cannot read tenant A's rows), so tenant isolation looks done. A pressure test then showed two tenants sharing one Postgres still collide.
- **Wrong first hypothesis:** adding `tenant_id` + `FORCE ROW LEVEL SECURITY` + a fail-closed policy predicate to every tenant table is sufficient for co-tenancy.
- **Root cause:** RLS controls row VISIBILITY, not physical key uniqueness. The tenant tables kept single-column business primary keys (`vessels.mmsi`, `watchlist.mmsi`, `sanctions_flags.id`). When tenant B upserts a key tenant A already holds, `ON CONFLICT (mmsi) DO UPDATE` conflicts with A's row, which is invisible to B under the policy, so Postgres raises SQLSTATE 42501; the API returns an unhandled 500, and the very failure is a covert channel telling B that another tenant holds that key. Worse, the tenant-private annotations (watchlist reason/severity, sanctions flags) are keyed only by MMSI, so tenants overwrite and read each other's private data. The CDC read side (a tenant-oblivious Debezium consumer feeding a DynamoDB table keyed on MMSI only, plus a tenant-agnostic Redis cache) has the same gap: Debezium bypasses RLS, so last-LSN-writer wins and cross-tenant reads leak.
- **Fix:** re-scoped the tenant tables to composite `(tenant_id, business_key)` primary keys with composite `ON CONFLICT` targets, added an explicit transactional migration with sentinel backfill and row-preservation checks, and carried the tenant dimension through Debezium envelopes, DynamoDB feature keys, `WatchlistLookup`, and Redis keys. The migration and runtime schema bootstraps share an advisory lock. Local PostgreSQL 16 tests proved same-MMSI isolation under RLS, two local production-image containers read only their tenant's values, and a fresh local kind stack passed the 4.28-second CDC smoke plus all five Phase 2 e2e criteria. The live AWS cutover still requires the human-run Postgres migration and a verified tenant-qualified DynamoDB/Redis rebuild in `docs/runbooks/P39_COMPOSITE_KEY_MIGRATION.md`.
- **Lesson:** RLS is a visibility filter layered on top of a schema; it does not make a globally-unique key per-tenant, and it does not reach a CDC replication stream that reads the WAL directly. Multi-tenant isolation is a property of the keys and every store in the pipeline, not of one policy on one plane. A drill that only exercises reads and no-tenant writes will certify an isolation model that a same-key upsert breaks.

---

## P40: Mutation testing on the shared working tree poisons __pycache__

**Tags:** [PLATFORM / personal-build] TOOLING

**Status: GROUNDED**; 2026-07-11, branch wave3-pressure-test (observed while remediating the Wave 3 sweep; `docs/WAVE3_FINDINGS.md`).

- **Symptom:** `test_tenant_drift` began failing after the adversarial sweep, in isolation, against source that `git diff` showed was unchanged. `inspect.getsource` printed the correct function body, yet the imported function returned a wrong (broken) result on the same objects.
- **Wrong first hypothesis:** a real logic bug in `drifted_tenants`, or a stray uncommitted mutation left in the source.
- **Root cause:** the sweep's mutation-testing lens edited source files in place to check whether a mutation survives, then reverted them. The reverts restored the source cleanly, but Python had already compiled `.pyc` bytecode from the MUTATED source into `__pycache__`, and its invalidation check did not trigger a recompile, so the interpreter loaded stale bytecode that no longer matched the (correct) source. `inspect.getsource` reads the `.py` and looked right; the running code came from the poisoned `.pyc`.
- **Fix:** cleared every `__pycache__` directory; the full suite went green. The lesson was recorded so future sweeps run with `PYTHONDONTWRITEBYTECODE=1` or clear the cache on exit.
- **Lesson:** any tool that rewrites source in place (mutation testing, codemods, autofixers) can leave `.pyc` files whose bytecode outlives the source it came from, and a test failing against source that reads correctly is the signature. When behavior contradicts the source you can see, suspect the bytecode cache before the logic.

## P41: An optional empty Terraform value is still an invalid AWS API value

**Tags:** [PLATFORM / personal-build] TOOLING

**Status: GROUNDED**; 2026-07-12, Wave 4 W3 live window (commit `86f3d63`, `infra/terraform/modules/kda_flink/main.tf`; fix verified in the same live window).

- **Symptom:** the Kinesis Data Analytics v2 application failed during `terraform apply` with `ValidationException: Member must have length greater than or equal to 1`, even though the empty `quarantine_bucket` value meant that quarantining was intentionally disabled.
- **Wrong first hypothesis:** an unrelated Flink application setting or Terraform provider serialization bug was producing a malformed request.
- **Root cause:** Terraform still serialized `quarantine_bucket = ""` into the Flink property map. Kinesis Analytics v2 rejects every zero-length property-map value; an empty string is not the same as an absent optional property at the AWS API boundary.
- **Fix:** constructed the property map with `merge()` and conditionally added `quarantine_bucket` only when it was nonempty. The Flink job already treats a missing property as disabled, so the change fixed the request without changing runtime semantics.
- **Lesson:** an optional value has two representations, absent and present-but-empty, and external APIs may accept only one. Model omission explicitly at the IaC boundary instead of assuming an empty string carries application-level meaning through every layer.

## P42: `.dockerignore` excluded the source tree a nested Dockerfile needed

**Tags:** [PLATFORM / personal-build] TOOLING

**Status: GROUNDED**; 2026-07-12, Wave 4 W3 image build (commit `86f3d63`, `.dockerignore` and `cdc/consumer/Dockerfile`; rebuilt successfully in the same window).

- **Symptom:** the first real CDC consumer image build failed at `COPY cdc ./cdc`; Docker reported that the source path was missing even though the directory existed in the repository.
- **Wrong first hypothesis:** the Dockerfile was using the wrong build context, or the image-build command pointed at the wrong directory.
- **Root cause:** the repository-level `.dockerignore` excluded the entire `cdc` tree from the build context. The Connect image had never exposed the mistake because its Dockerfile downloads a JAR and copies no local CDC source, while the consumer Dockerfile imports the package and must copy it.
- **Fix:** removed the blanket `cdc` exclusion and documented why that tree must remain in the context, matching the existing carve-out for another locally imported package.
- **Lesson:** build-context filters are shared dependencies across every Dockerfile that uses the context. A successful sibling image proves nothing if it copies a different subset of the repository; test each real Dockerfile against the exact context it will receive.

## P43: Private DNS made one endpoint security group a VPC-wide dependency

**Tags:** [PLATFORM / personal-build] NETWORKING SECURITY

**Status: GROUNDED**; 2026-07-12, Wave 4 W3 live CDC deployment (commit `86f3d63`, `infra/terraform/modules/cdc_monitoring/main.tf`; the Debezium task retrieved its secret after the live fix).

- **Symptom:** the Debezium Fargate task failed during startup with `ResourceInitializationError`; `GetSecretValue` timed out even though the task had the right Secrets Manager permission and outbound network access.
- **Wrong first hypothesis:** the secret ARN, task execution-role policy, or ECS secret injection configuration was wrong.
- **Root cause:** the monitoring module created private-DNS interface endpoints for Secrets Manager and CloudWatch. Those DNS names resolve to the endpoint ENIs for every client in the VPC, but the endpoint security group allowed port 443 only from the slot-lag Lambda security group. Debezium was routed to the endpoint and silently blocked at ingress.
- **Fix:** allowed HTTPS ingress from the VPC CIDR, consistent with the endpoint's VPC-wide private-DNS scope and the convention used by the other modules.
- **Lesson:** enabling private DNS changes the network path for the whole VPC, not just the resource that created the endpoint. The endpoint security group's trust scope must cover every intended in-VPC caller or valid IAM requests will look like unexplained network timeouts.

## P44: MSK's data plane uses `kafka-cluster:*`, not `kafka:*`

**Tags:** [PLATFORM / personal-build] SECURITY TOOLING

**Status: GROUNDED**; 2026-07-12, Wave 4 W3 live CDC deployment (commit `86f3d63`, `infra/aws/harbormaster-permissions-boundary.json`; boundary policy v2 applied live and the Connect worker authenticated to MSK and joined its group).

- **Symptom:** the Connect worker crash-looped with `SaslAuthenticationException`, and ECS Exec was unavailable, even though its task role contained the expected MSK IAM and session-channel permissions.
- **Wrong first hypothesis:** the task-role policy, MSK bootstrap configuration, or IAM SASL client properties were incomplete.
- **Root cause:** the permissions boundary is an intersection, so task-role allows outside the boundary are effective denies. The boundary allowed `kafka:*`, the MSK control-plane namespace, but omitted `kafka-cluster:*`, the MSK IAM data-plane namespace. It also omitted `ssmmessages:*`, which ECS Exec needs for its channels.
- **Fix:** added both namespaces to the boundary and applied it as policy version v2. The worker then authenticated to MSK and joined its consumer group, and the live debugging channel became available.
- **Lesson:** AWS service permissions can be split across similarly named IAM namespaces, and a permissions boundary must admit every namespace used by the workload. Validate effective permissions at the intersection, not by reading the task role alone.

## P45: An unquoted remote heredoc erased a secret-provider reference before validation

**Tags:** [PLATFORM / personal-build] TOOLING SECURITY

**Status: GROUNDED**; live symptom observed 2026-07-12 in the Wave 4 W3 window, root cause reproduced and fix verified locally the same day (commit `159da26`, `cdc/connector/registration.py`, test `cdc/tests/test_connector_registration.py`, transcript `docs/drills/CDC_connector_registration_local_2026-07-12.md`). The corrected command has not been retried on AWS.

- **Symptom:** Debezium connector validation reported an empty database password in separate attempts using `${env:...}` and `${dir:...}` references. The ECS-injected secret existed, and the tmpfs file used by the `dir` attempt contained 28 bytes.
- **Wrong first hypothesis:** Kafka Connect 3.7 was resolving ConfigProvider references after `Connector.validate()`, or the Debezium image's providers were broken at validation time.
- **Root cause:** the runbook sent connector JSON through an unquoted remote Bash heredoc. Bash expanded `${env:...}` and `${dir:...}` as shell parameter expressions before `curl` ran, so Kafka Connect received an empty string and never saw a provider placeholder. Kafka 3.7 source confirmed that worker-side transformation happens before connector validation.
- **Fix:** base64-encoded the JSON locally, decoded it inside the remote command, and posted the decoded bytes with `--data-binary @-`. The regression test runs the real shell and HTTP transport and proves the placeholder survives. A fresh local Debezium 2.7 and Connect 3.7 stack reached connector and task state `RUNNING` and passed all five Phase 2 checks.
- **Lesson:** when a downstream parser appears to erase syntax, inspect every upstream interpreter first. Secret references are code-like strings, and shell transport must preserve their bytes exactly; encode the payload instead of layering fragile quoting rules.

## P46: A rolling ECS deployment leaves two plausible task ARNs

**Tags:** [PLATFORM / personal-build] CONCURRENCY TOOLING

**Status: GROUNDED**; operational finding from the 2026-07-12 Wave 4 W3 live window (commit `86f3d63`, `docs/runbooks/WAVE4_LIVE_WINDOWS.md`). This is the sixth W3 finding and a runbook correction, not a code-path fix.

- **Symptom:** an ECS Exec check appeared to prove that a just-deployed configuration change had not taken effect; the inspected task still showed the old environment and behavior after a successful apply.
- **Wrong first hypothesis:** Terraform or ECS had ignored the new task definition, or the replacement task had started with stale configuration.
- **Root cause:** ECS rolling deployment temporarily ran the old and new tasks together. A task ARN captured before the apply still identified a valid running task, but it was the retiring revision, so subsequent checks interrogated the wrong container.
- **Fix:** changed the runbook to re-fetch the current `RUNNING` task ARN after every apply before executing diagnostics.
- **Lesson:** in a rolling deployment, `RUNNING` proves liveness, not freshness. Treat task identity as ephemeral after every deployment and re-fetch it before collecting diagnostic evidence.
