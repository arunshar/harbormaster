# Harbormaster session handoff - 2026-07-03 (Phase 2 CDC local-stack ACCEPTED)

## One-line state
Phase 2 (the CDC pipeline, the resume-critical gap-closer) is LOCAL-STACK
ACCEPTED on branch `phase2-cdc` (off `phase1-aws-gates`): one commit per gate
2.0-2.9, the same-day adversarial-review fix pass (`3d55bae`, 17 confirmed
findings from a 24-agent review), AND the live local-stack run (same day,
later session): `make cdc-up` after a Strimzi 0.45.0 -> 1.1.0 fix (`ea22df4`;
0.45's fabric8 client cannot parse the k8s 1.36 /version response,
`emulationMajor`; Kafka CRs migrated to `kafka.strimzi.io/v1`), the envelope
fixture RE-RECORDED from the live topics and re-pinned with an identical
census (`d38a0fe`, new `scripts/cdc_record_fixture.py`), smoke insert-to-online
0.57 s vs the 5 s target, and `make cdc-e2e` = ALL FIVE acceptance criteria
green in one run (transcript `docs/drills/E2E_local_stack.md`); teardown
clean. Suite 180 passed / 9 skipped, ruff clean. What remains is the Arun-run
AWS showcase demo apply only, scripted end-to-end in
`docs/runbooks/PHASE_2_AWS_SHOWCASE.md`. Phase 1 infra untouched except the
two deliberate serving-module fixes recorded in the addendum (the task
definition now actually injects Postgres config; DB_SECRET_ARN was read by
nothing).

## What Phase 2 delivered (commits on phase2-cdc)
- **2.0** (`8b891e4`): `docs/phases/PHASE_2.md` (the ultra-detailed gate plan,
  invariants 1-5, cost envelope, scope guard) + `enable_phase2` toggle (default
  false); plan with both toggles false verified as No changes.
- **2.1** (`ccb5594`): `cdc/schema/ddl.py` (idempotent DDL: `vessels`,
  `watchlist`, `sanctions_flags`, REPLICA IDENTITY FULL, explicit
  `harbormaster_cdc` publication; SHA256-pinned), `serving/app/registry.py`
  (memory + asyncpg backends mirroring hitl.py), `/v1/registry/*` routes,
  Streamlit console Registry tab. Postgres stays the system of record; the API
  never writes the online store.
- **2.2** (`f000b06`): `serving/app/watchlist.py` WatchlistLookup: one DynamoDB
  Query per vessel (entity_id = mmsi -> vessel_meta + watchlist + sanctions:*),
  Redis read-through with invalidation as the freshness path (TTL backstop
  300 s), soft-delete markers read as absent, FAIL-OPEN + counter. New reasons
  WATCHLIST_HIT (0.9) / SANCTIONS_HIT (0.95) via the existing noisy-OR; lookup
  disabled by default so Phase 1 goldens are byte-identical (asserted).
- **2.3** (`e5624cb`): `cdc/consumer/envelope.py` (c/u/d/r + tombstone +
  heartbeat/schema-change skips + schema-wrapped unwrap; LSN mandatory),
  `cdc/connector/config.py` (pgoutput connector JSON generator + drift
  validator: autocreate disabled, table list == DDL surface, tombstones on,
  heartbeat 10 s). Hand-authored Debezium 2.7 envelope fixture, SHA-pinned
  (re-record at the local-stack run).
- **2.4** (`64ac396`): `cdc/consumer/applier.py` + `cdc/sinks/base.py`: the
  LSN-guarded idempotent applier (apply -> flush all sinks -> commit; sink
  failure leaves offsets uncommitted), whole-item puts + per-(table,pk)
  monotonic guard => any delivery schedule converges (25-seeded-schedule
  property test), canonical soft-delete markers (no resurrection), audit =
  transport truth with the guard verdict. Final-state golden pinned.
- **2.5** (`b23f07e`): real sinks. `cdc/sinks/dynamo.py` (conditional PutItem,
  `attribute_not_exists(last_applied_lsn) OR last_applied_lsn < :lsn`, into the
  Phase 0 feast_online layout; lockstep-tested against the reference sink and
  parse-back-tested through the serving reader), `redis_cache.py` (DEL
  hm:online:<mmsi> on applied only), `iceberg_audit.py` (buffered, flush on
  batch ack, requeue on writer failure; SQLite catalog local / Glue + S3 lake
  on AWS). New `[cdc]` extra.
- **2.6** (`cd7cad3`): `cdc/consumer/service.py` ConsumerLoop (manual
  commit-after-sink-ack, SIGTERM drain, Prometheus counters, MSK IAM config) +
  consumer Dockerfile + the local plane under `deploy/k8s/cdc/` (kind
  NodePorts, Strimzi KRaft Kafka, Debezium Connect as a plain Deployment
  [decision recorded], Postgres 16 logical, Redis, DynamoDB Local) +
  `scripts/cdc_smoke.py` + make cdc-up/cdc-down/cdc-smoke/cdc-consumer.
- **2.7** (`de6bc1c`): AWS showcase Terraform behind `enable_phase2`:
  `msk_serverless` (~$18/day COST WARNING, demo windows only), `ecs_connect`
  (Debezium + aws-msk-iam-auth via `cdc/connect/Dockerfile`; RDS password via
  ECS secret + EnvVarConfigProvider), `ecs_cdc_consumer`, `redis_fargate`
  (containerized; ElastiCache documented as prod choice), `cdc_monitoring`
  (1-min slot-lag Lambda -> Harbormaster/CDC metrics -> alarm with
  missing-data=breaching -> FinOps SNS). rds module gains inert-by-default
  `logical_replication`. `make cdc-lambda-package` vendors pg8000.
  CHECKSUMS (post-review-fix): both-false plan = No changes; both-true =
  67 add / 0 change / 0 destroy (connect/consumer services additionally
  gated on image vars; their ECR repos exist whenever enable_phase2 is on).
- **2.8** (`60cc808`): DRILLS RUN LIVE. P1 (real postgres:16 container): an
  undrained pgoutput slot pinned 0 -> 74,038,888 WAL bytes over 5 rounds,
  monotonic; alert fired; drain collapsed to 0. P2 (real applier): crash-replay
  and zombie-rebalance schedules converge byte-identically under the guard; the
  no-guard sink double-applies 5 writes and regresses severity 0.95 -> 0.9
  (stale data wins). Transcripts `docs/drills/P1_slot_bloat.md` +
  `P2_duplicates.md`; PLATFORM_WAR_STORIES.md P9 + P10 grounded; mirrored to
  arunshar/debug-war-stories as #85 + #86 (pushed). Consumer gained the
  HM_DRILL_NO_GUARD flag (refused without HM_DRILL=1).
- **2.9**: `tests/e2e/test_phase2.py` (HM_CDC_E2E-guarded; pure helpers
  unit-tested) encoding the five acceptance criteria: (a) flag-to-scored
  within ~5 s, (b) fresh-group full replay leaves the online-state hash
  unchanged, (c) Debezium restart loses no change (HM_CDC_RESTART_CMD), (d)
  delete -> offline + scorer stops flagging, (e) a stalled slot's lag alert
  fires live. `make cdc-e2e` with local-stack defaults. HONESTY.md Multigres
  section updated to shipped-CDC language.

- **review fix pass** (`3d55bae`): 17 confirmed findings fixed. Highlights:
  snapshot rows apply at a floor guard LSN of 0 (spanning-transaction updates
  can never be lost); poison events are counted + audited + skipped instead of
  crash-looping the consumer, and the poison sanctions id is unmintable at
  every layer (API validators, id producers, DDL CHECKs); Redis invalidation
  fires per delivered event; the scorer's lookup runs off the event loop with
  1 s fail-fast timeouts; the serving task definition finally injects real
  Postgres config (fixing a silent Phase 1 memory-fallback defect); the
  slot-lag Lambda gets Secrets Manager + CloudWatch interface endpoints (it
  had no route to either API in the NAT-less VPC); CDC ECR repos moved out of
  the image-gated modules (push-then-apply works); drill P1 uses a drill-only
  slot; the replay e2e can no longer pass vacuously. Goldens re-pinned.

Full suite: **179 passed / 9 skipped** (5 phase-2 e2e + 2 phase-1 e2e +
2 postgres opt-ins), ruff clean, terraform fmt + validate clean.

## Environment / access (unchanged from the Phase 1 handoff)
Repo `~/code/harbormaster` ONLY. AWS 645322802947, us-east-1 (pass --region).
CLI = IAM arun-admin. State in S3. $75 hard cap live; alerts to
arunshar@umn.edu. `terraform apply` is Arun-run; Claude does plan/validate/
code/tests. No Claude co-author, no em dashes, paste-ready in fenced blocks.

## Remaining to declare Phase 2 DONE
1. Local: DONE 2026-07-03. `make cdc-up` (Strimzi 1.1.0 after the fix) ->
   fixture re-record + re-pin -> `make cdc-smoke` 0.57 s PASS ->
   `make cdc-consumer` + `make serve-run-cdc` -> `make cdc-e2e` 5/5 PASSED
   (33.5 s) -> `make cdc-down`. Transcript `docs/drills/E2E_local_stack.md`;
   findings folded into the PHASE_2.md local-stack run addendum + the master
   plan per governance.
2. AWS showcase (Arun-run, demo window): follow
   `docs/runbooks/PHASE_2_AWS_SHOWCASE.md` end to end (lambda package ->
   toggles-only apply -> image build/push with --platform linux/amd64 ->
   image-vars apply -> in-VPC connector registration via ECS exec -> the five
   criteria via laptop-reachable primitives -> teardown by flipping
   enable_phase2 false + `make apply`). NEVER `make destroy`.
3. Push `phase2-cdc` when Arun says push.
4. Cover-note follow-up: RESOLVED 2026-07-03. The file had been deleted in a
   cleanup (with its two supabase-multigres-deep-dive companions and the skill
   folder's .git); all three were recovered byte-exact from the 2026-06-19
   session transcripts (the original Write tool records) back into
   ~/.claude/skills/temporal-interview-prep/references/, the cover note's gap
   paragraph was updated to the shipped-CDC wording, and the restored files
   were pushed to the private temporal-prep-arc backup repo.

## Resume prompt for the next session
Load memory (project_harbormaster) + the arun-session-handoff skill + this
file + docs/phases/PHASE_2.md. Phase 2 is LOCAL-STACK ACCEPTED on phase2-cdc
(unpushed; push gated on Arun). Next actions: (a) walk Arun through the AWS
showcase per docs/runbooks/PHASE_2_AWS_SHOWCASE.md when he opens a demo
window (Claude preps plans/commands; Arun runs applies), and (b) push
phase2-cdc when Arun says push. After the showcase, log any new war stories
and start Phase 3 planning (lake + Pi-DPM async endpoint) per the master
plan.
