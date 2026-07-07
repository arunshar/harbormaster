# AB Masterclass audit

## What this is

Harbormaster graded against the sixteen system-design principles of the Arpit Bhayani System Design Masterclass (dimensions D1-D16, cross-checked against the `ab-system-design` note set). It is a design-review artifact meant to be read first by a skeptical principal engineer or an international/defense buyer: it says plainly where the platform is production-shaped, where it is only documented, and where it deliberately builds nothing.

**How it was produced.** A read-only multi-agent audit distilled the masterclass into a sixteen-dimension rubric, then walked the Harbormaster codebase against it. Every high-stakes finding was hand-verified against the actual code at the cited `file:line`. Two honesty rails govern every row: a capability that is documented but never run caps at **Partial** (a "COMPLETED" design is not a result), and an item that `docs/HONESTY.md` declares out of scope is marked **Out-of-scope-by-design**, not a gap.

**The net grade.** Harbormaster is a genuinely well-engineered, honestly-scoped personal platform. Its **CDC plane is production-shaped**: real Postgres logical replication, an idempotent LSN-guarded sink, and a property-tested convergence model. Its pure logic across the lake, serving, and MLOps planes is densely tested. The load-bearing gaps concentrate in five clusters: **streaming exactly-once/windowing** (delegated to managed Flink, untested), **SLO burn-rate** (self-admittedly never built, which disables auto-rollback), **API-gateway exposure plus IAM blast radius** (the security front door), **lakehouse compaction/idempotency**, and the **credibility artifacts** (this doc and its companion ADRs). All but the true AWS-spend items are closable locally.

This document cross-links each dimension to its decision record in `docs/SYSTEM_DESIGN_DECISIONS.md` and does not restate the reasoning there. It adds the one column that catalog lacks: **run versus documented**.

---

## The matrix

Status legend: **Solid** (built and tested), **Partial** (real but incomplete, or documented-not-run), **Gap** (missing against the bar), **Out-of-scope-by-design** (declared out in `docs/HONESTY.md`, not counted as a gap). The ★ dimensions are the six load-bearing walls for a streaming + CDC + lakehouse + ML-serving platform; each cites the grounding AB note.

| Dimension | DR entry | Status | Run vs Documented | Evidence (file:line) | Remediation pointer |
|---|---|---|---|---|---|
| **D1. Capacity estimation** ★ (AB note `01`/`02`/`10`/`13`) | DR-14 | Partial | Score kernel: measured locally (extrapolated to fleet/$). Ingest/storage: Documented | `bench/SCORE_BENCH.md` + `bench/bench_score.py`: measured on Apple M4 Pro (local dev Mac, arm64), single-event golden path p95 ≈ 0.61 ms, ≈ 1,760 scores/sec/core, $/inference ≈ 3e-9 (extrapolated onto the `cost.py` Fargate rate, not a measured cloud figure); design estimates `SYSTEM_DESIGN_DECISIONS.md:297-334` (10K/30K msg/s, 30-40 shards, 12-15 TB/yr), honesty caveat `:330`; `EXPERIENCE_REPORT.md:73`; `PLATFORM_BOOK.md:341` | Top remediation (b)5: DONE for the score kernel (`bench/SCORE_BENCH.md`); remaining = a cloud-instance load test to replace the $/inference extrapolation with a measured AWS figure, plus an ingest/storage throughput test |
| **D2. Single-node performance** | (no dedicated DR) | Solid | Run (tested) | `features/features.py`, `orchestrator.py` deterministic CPU/NumPy path; golden `latency_ms < 200ms` `test_golden.py:27`; `slo.py:27` p95≤300 | Minor: add one `py-spy`/`cProfile` hot-path capture to `bench/` |
| **D3. Relational modeling, locking, indexing** | DR-4 (write model) | Partial | Run (upserts) / Documented (locking) | `registry.py`; `INSERT…ON CONFLICT` `hitl.py:132`, `registry.py:138`; `wal_level=logical` `10-postgres.yaml:23`; RLS design-only `PLATFORM_BOOK.md:207` | ADR: state no fixed-inventory contention exists, OR add `SELECT … FOR UPDATE SKIP LOCKED` on HITL dequeue + test |
| **D4. Access-pattern-first / denormalization** ★ (AB note `04`/`08`/`16`) | DR-4 | Solid | Run (CQRS split live) | CQRS split `registry.py:1-6`, `watchlist.py:1-9`; point-in-time `merge_asof` `export_training_set.py:23` | Minor: add a read→store→key paragraph to `SYSTEM_DESIGN_DECISIONS.md` |
| **D5. Replication / consistency / CAP-PACELC** | DR-16, DR-1 | Partial | Run (single-partition CDC) / Documented (MSK, rebalance) | CDC LSN guard `applier.py`, `sinks/base.py:68`; `ConsistentRead=False` `watchlist.py:11`; MSK path never ran `PLATFORM_BOOK.md:143`; single partition (`tasks.max=1`) | Top remediation (a)2: local ≥2-partition + rebalance test; ADR on CDC staleness budget |
| **D6. Partitioning / sharding** ★ (AB note `02`/`06`/`12`) | DR-9 | Partial | Run (key chosen) / Documented (hot-shard mitigation, lake partitioning) | MMSI→Kinesis key `ingest.py:47`→Flink `key_by` `job.py:391`; hot-shard P1 anticipated only (`PLATFORM_WAR_STORIES.md`); lake written unpartitioned `iceberg.py:18-30` | Top remediation (a)3: explicit-hash spreading + skew test; Iceberg partition spec on the writer |
| **D7. Consensus / quorum / leader election / locks** | none (HONESTY.md scope-out) | Out-of-scope-by-design | N/A | `HONESTY.md:31-34` (no Raft, Paxos, or consensus; coordination via managed services) | None. Keep the disclaimer; optionally cite Kleppmann ch9 + Chubby in an ADR |
| **D8. Fault tolerance & failure detection** | DR-8 (async), DR-13 (detection) | Partial | Run (CDC/serving) / Gap (streaming DLQ, scorer POST) | Slot-lag Lambda `treat_missing_data="breaching"` (`cdc_monitoring/main.tf`); malformed AIS dropped `job.py:323`, `live.py:64`; scorer POST fire-and-forget `job.py:361`; unresolved async gap `PLATFORM_BOOK.md:340` | Top remediation (a)1: real DLQ sink + retry-with-DLQ on the scorer POST |
| **D9. Distributed ID generation** | DR-15 (idempotency keys) | Solid | Run (tested) | Composite keys `"<mmsi>:<regime>"` with Postgres `CHECK` `ddl.py:97`; replay-stable `trace_id` drives HITL idempotency | None material. Optionally note in ADR why no Snowflake/ULID is needed |
| **D10. Storage engines: LSM / WAL / compaction / amplification** ★ (AB note `10`/`11`) | DR-5, DR-12 | Partial | Run (writer) / Gap (compaction, idempotency) | Iceberg writer real `iceberg.py:65`; rotating local WAL in ingestor; no compaction/snapshot-expiry/partition-spec, `table.append` double-writes on re-run `iceberg.py` | Top remediation (a)3: run-level dedup key + compaction + `expire_snapshots` + partition spec |
| **D11. High-throughput: batching / async / backpressure / exactly-once / idempotency** ★ (AB note `02`/`08`/`11`) | DR-2 (CDC), DR-6 (backpressure) | Partial | CDC: Run (Solid). Streaming: Documented (Gap) | CDC apply→flush→commit `applier.py:86-103`, 25-schedule convergence property test `test_applier.py:292`, `enable.auto.commit=False`; streaming per-event `KeyedProcessFunction` no window/watermark/checkpoint `job.py:38-40`; Kinesis put retries once no backoff `ingest.py:139` | Top remediation (a)1: real windowing + checkpointing OR honest relabel; exp-backoff on Kinesis putter; tests instantiating `FeatureProcess` |
| **D12. Caching: patterns / invalidation / hot keys / stampede** | DR-4, DR-16 | Partial | Run (cache-aside) / Gap (stampede, negative-lookup) | Cache-aside write-invalidate `redis_cache.py`; read-through TTL, fail-open `watchlist.py:235`; no request-coalescing on miss; no negative cache | Top remediation (a)4: per-key single-flight lock + optional negative cache + test |
| **D13. Information retrieval / search / indexing** | none (N/A for this workload) | Out-of-scope-by-design | N/A | No search surface; workload is point-lookup + scoring, not corpus search | None. Stated N/A: single-vessel scoring, not IR |
| **D14. Rate limiting / load shedding / throttling** ★ (AB note `12`/`16`) | DR-6 (P_phys shed) | Gap | Run (corrupt-gate) / Gap (front door open) | Corrupt-gate 422 `orchestrator.py:327`; public API Gateway no authorizer/WAF/throttling/access-logging `modules/apigw/main.tf`; no concurrency limit on `/v1/score-ais` | Top remediation (b)2: API GW throttling + access logging + authorizer (Terraform-only); bounded scorer queue |
| **D15. Observability & operability** | DR-13 | Partial | Run (dashboards/alarms) / Gap (traces, burn-rate) | HITL/task lifecycle columns; CloudWatch dashboard + 2 SLO alarms; slot-lag alarm best-designed; no X-Ray/OTel (doc-vs-code drift `PHASE_1.md:78`); `$/inference` EMF not wired | Top remediation (b)1: real windowed burn-rate calculator; add OTel spans or correct the doc claim |
| **D16. Algorithmic design: probabilistic structures / reduction / geo-indexing** | none (no dedicated DR) | Partial | Run (clustering) / Gap (geo-index, bloom, HLL) | HDBSCAN waypoint clustering + RDP `transforms.py`; no GeoHash/spatial index, no bloom on negative-lookup, no HLL | GeoHash prefix index for corridor/proximity + test; bloom into watchlist negative-lookup (ties D12) |

### Cross-cutting infra / security / governance

Folded from the gap matrix and graded against the principal-engineer-plus-international-buyer bar the review sets.

| Dimension | DR entry | Status | Run vs Documented | Evidence (file:line) | Remediation pointer |
|---|---|---|---|---|---|
| **Least-privilege / IAM blast radius** | DR-7 (default-deny, tenant) | Gap | Run (over-privileged) | `harbormaster-platform` = `PowerUserAccess` + `iam:PassRole/AttachRolePolicy/CreateRole` on `*` `bootstrap.sh:116-122`, `harbormaster-platform-permissions.json:5-42` | Top remediation (b)3: permissions boundary + path-scoped IAM management |
| **DR / multi-region / backup** | DR-13 (posture context) | Out-of-scope-by-design (posture) / Gap (documentation) | Documented (RPO/RTO absent) | `multi_az=false`, `backup_retention=1`, `skip_final_snapshot=true` `rds/main.tf`; "entire footprint is us-east-1" `PLATFORM_BOOK.md:151` | Top remediation (b)4: RPO/RTO + DR-scope ADR; do NOT claim DR you don't have |
| **Encryption / KMS / data residency** | (no dedicated DR) | Partial | Run (SSE) / Gap (CMK, in-transit) | S3 SSE-AES256, RDS `storage_encrypted`, DynamoDB PITR; no CMK; slot-lag Lambda `CERT_NONE` `cdc_slot_lag/handler.py` | Top remediation (b)4: pin RDS CA bundle in the Lambda (removes `CERT_NONE`); CMK module for buyer-grade path |
| **IaC governance / CI** | DR-11 (phased build) | Gap | Documented (engineering-standard) / Gap (enforcement) | Terraform outside CI; no `validate`/`plan`/tfsec/checkov/tflint; no coverage gate, mypy, bandit, `.pre-commit-config.yaml`; account id hardcoded `backend.tf` | Top remediation (a): CI job `terraform fmt/validate` + tflint + tfsec/checkov; `--cov-fail-under=90`, mypy, bandit, pre-commit |
| **Promotion actuators / burn-rate signal** | DR-3, DR-13 | Gap | Documented (state machine tested against fakes) / Gap (no live actuator or signal) | `set_canary_weight`/`revert_to_champion`/`burn_check` never bound to SageMaker; `slo.py` = 3 static thresholds; burn-rate never implemented `PLATFORM_BOOK.md:76`; single-variant endpoint (canary traffic-inert) | Top remediation (b)1: windowed burn-rate calculator feeding `burn_check`; wire `set_canary_weight` to a two-variant endpoint OR relabel as traffic-inert by design |

---

## What we deliberately do not build, and why

The point of this section is that a skeptical reader never has to guess whether something is missing or scoped out. Each item below is a deliberate boundary, stated up front.

- **Consensus (Raft / Paxos) and a sharded query router.** `HONESTY.md:31-34` declares both explicitly out of scope: "Harbormaster does not implement query sharding or a routing layer across shards" and "does not implement Raft, Paxos, or any consensus protocol. Where coordination is needed it uses managed services, and that reliance is stated plainly." This is Vitess/Multigres territory; Harbormaster consumes managed Postgres and managed brokers rather than re-implementing coordination. If asked whether the platform proves a consensus system or a sharded router, the honest answer is no (D7 above; `HONESTY.md:34`).
- **Multi-region DR as a running system.** Single-region us-east-1 is a declared cost posture on a $75/month account (`multi_az=false`, `backup_retention=1`), not an oversight. The real gap is documentation, not architecture: the RPO/RTO numbers must be written down even though the answer is "single-region by design." A buyer needs the numbers; do not claim DR that does not exist.
- **The phase3-demo-standin model.** The SageMaker endpoint served a labeled `phase3-demo-standin` throughout the live showcase, never a real trained checkpoint (`HONESTY.md:63`). The claim supported is the infrastructure and promotion discipline, not model quality. The label stays.
- **Simulated personas, clients, and FDE scenarios.** Every customer narrative carries an inline `SIMULATED` label per the `HONESTY.md:41` labeling rule. These are never presented as real engagements.
- **Information retrieval / search (D13).** N/A for this workload: Harbormaster does single-vessel scoring and point-lookup serving, not corpus search. No Elasticsearch surface is built, and none is needed. Stated, not silently absent.

---

## Top remediations

Mirrors the three gap-matrix buckets. Each item points at the phased plan in the gap matrix (Part 2); none recommends *claiming* a capability, only building it locally, proving it with spend, or labeling it out loud.

### (a) Real correctness / robustness (local, no spend)

1. **Streaming exactly-once / DLQ / backpressure is a demo realization, not a system.** `job.py` has no window, watermark, or checkpoint; the scorer POST is fire-and-forget with failures swallowed (`job.py:361`); no DLQ for malformed AIS; `job.py` untested. Fix: exp-backoff on the Kinesis putter (`ingest.py:139`), a real DLQ sink, tests instantiating `FeatureProcess` + keyed state, and either real windowing/checkpointing against a local Flink mini-cluster **or** an honest relabel. (D8, D11.)
2. **CDC idempotency ordering is unproven at real partition scale.** The per-key LSN guard is property-tested at single-partition (`test_applier.py:292`) but never at ≥2 partitions with a rebalance. Fix: a local Strimzi/kind multi-partition + rebalance test. (D5, D6.)
3. **Lake backfill has no cross-run idempotency and no compaction.** `table.append` double-writes on re-run; no MERGE, snapshot expiry, or partition spec (`iceberg.py`), the textbook lakehouse small-file failure. Fix: run-level dedup key + compaction/`expire_snapshots` + partition spec, all local pyiceberg. (D6, D10.)
4. **Cache stampede on watchlist misses.** No request-coalescing; each concurrent miss hits DynamoDB. Fix: per-key single-flight lock + optional negative cache. (D12.)

### (b) Production guarantees

1. **SLO burn-rate + error-budget alerting does not exist.** `slo.py` is three static thresholds; `burn_check` had no real signal source (`PLATFORM_BOOK.md:76`), which disables auto-rollback. The single most-cited internal honesty gap. Fix: a windowed multi-window burn-rate calculator (pure Python) feeding both alarms and `burn_check`. (D15; promotion actuators.)
2. **Public unauthenticated API Gateway, no throttling/WAF/access logs** (`modules/apigw/main.tf`). The rubric's most-critical ML-serving dimension is wide open. Fix: authorizer + throttling + access logging (Terraform-only, no spend at rest). (D14.)
3. **IAM deploy identity is admin-equivalent** (`PowerUserAccess` + `iam:PassRole` on `*`). A regulated/international buyer fails this at the first checklist item. Fix: permissions boundary + path-scoped IAM management. (IAM blast radius.)
4. **DR / residency: state the RPO/RTO even though single-region is the chosen posture.** Fix: a DR + residency ADR; RDS CA-bundle cert fix removing `CERT_NONE`. (DR/multi-region; encryption/KMS.)
5. **Capacity planning has no load test.** Every number is an estimate. Fix: one committed local load-test transcript for `/score` and one measured $/inference. (D1.)

### (c) Credibility / documentation (completed in this pass, 2026-07-06)

1. **This file, `docs/AB_MASTERCLASS_AUDIT.md`,** is the first-class design-review artifact folding the matrix in as a repo deliverable; it cross-references `SYSTEM_DESIGN_DECISIONS.md` without restating it and cites AB notes for the load-bearing six.
2. **ADRs** in `docs/adr/` for the previously-implicit decisions: streaming realization (per-event vs windowed), CDC staleness budget, single-region DR (RPO/RTO), no-consensus/no-sharded-router (cites `HONESTY.md`). Each ADR closes a documented-not-demonstrated row.
3. **War stories tagged ANTICIPATED vs GROUNDED.** `PLATFORM_WAR_STORIES.md` mixed anticipated stories (P1-P8) with grounded ones; a buyer-grade artifact must not let anticipated stories read as observed. Each P1-P8 now carries a one-line tag, matching the `HONESTY.md` discipline.
4. **Two doc-drifts resolved:** Bedrock, described as current architecture in `ARCHITECTURE.md:71`, is now labeled a Phase-5 planned item consistent with `PLATFORM_BOOK.md`; the OTel tracing claimed in `PHASE_1.md:78` is now labeled a planned gate target that was not implemented (no OTel/X-Ray in the code). Both were credibility landmines under a skeptical read.

Where `SYSTEM_DESIGN_DECISIONS.md` already covers a dimension well (D1 estimation `:297-334`, D4/D16 CQRS/PACELC DR-4/DR-16, D11 CDC idempotency DR-2, D12 lambda/kappa DR-12), this audit links to those DR entries and adds only the run-versus-documented column the DR catalog lacks.
