# Harbormaster session handoff - 2026-07-03 (Phase 2 CDC code-complete)

## One-line state
Phase 2 (the CDC pipeline, the resume-critical gap-closer) is CODE-COMPLETE on
branch `phase2-cdc` (off `phase1-aws-gates`), one commit per gate 2.0-2.9, with
both drills RUN LIVE and war stories P9/P10 grounded. What remains is
stack-run-time only: the local kind/Strimzi bring-up + smoke + e2e, and the
Arun-run AWS showcase demo apply. Phase 1 is untouched (deploy-only, as before).

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
  CHECKSUMS: both-false plan = No changes; both-true = 62 add / 0 change /
  0 destroy (Phase 1 = 43, Phase 2 adds 19; connect/consumer additionally
  gated on image vars).
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

Full suite: **178 passed / 9 skipped** (5 phase-2 e2e + 2 phase-1 e2e +
2 postgres opt-ins), ruff clean, terraform fmt + validate clean.

## Environment / access (unchanged from the Phase 1 handoff)
Repo `~/code/harbormaster` ONLY. AWS 645322802947, us-east-1 (pass --region).
CLI = IAM arun-admin. State in S3. $75 hard cap live; alerts to
arunshar@umn.edu. `terraform apply` is Arun-run; Claude does plan/validate/
code/tests. No Claude co-author, no em dashes, paste-ready in fenced blocks.

## Remaining to declare Phase 2 DONE (stack-run-time)
1. Local: `make cdc-up` (kind + Strimzi + Debezium + pg + redis + ddb-local;
   first run pulls images), then `make cdc-smoke` (registers the connector,
   runs the consumer, times insert-to-online vs the 5 s target). While the
   stack is up: re-record `cdc/fixtures/debezium_envelopes.jsonl` from the
   live topics and re-pin its SHA (documented diff vs the hand-authored one),
   run the serving API locally pointed at DynamoDB Local
   (HM_ONLINE_TABLE=hm-local-feast-online HM_DDB_ENDPOINT_URL=http://127.0.0.1:30800
   HM_REDIS_URL=redis://127.0.0.1:30379/0 HM_PG_DSN=postgresql://hm_admin:hm_local_pw@127.0.0.1:30432/harbormaster
   make serve-run), then `make cdc-e2e` (all five criteria in one run;
   transcript to docs/drills/). Teardown `make cdc-down`.
2. AWS showcase (Arun-run, demo window): `make cdc-lambda-package`; build +
   push `cdc/connect/Dockerfile` and `cdc/consumer/Dockerfile` to the ECR
   repos (created by the apply); set enable_phase1=true enable_phase2=true +
   cdc_connect_image/cdc_consumer_image in tfvars; `make apply`; register the
   connector (ecs exec / in-VPC task, db_password="$${env:HM_PG_PASSWORD}");
   run the e2e with env pointed at the demo; teardown by flipping both toggles
   false + `make apply`. NEVER `make destroy`.
3. Push `phase2-cdc` when Arun says push.
4. Cover-note follow-up: the tracked file
   temporal-interview-prep/references/supabase-multigres-cover-note.md does
   NOT exist on disk (stale memory pointer). The shipped-CDC gap language now
   lives in docs/HONESTY.md ("Multigres cover-note update"); Arun points at
   the real cover-note location (Gmail draft / Google Doc?) and it gets the
   same edit.

## Resume prompt for the next session
Load memory (project_harbormaster) + the arun-session-handoff skill + this
file + docs/phases/PHASE_2.md. Phase 2 is code-complete on phase2-cdc; do the
local-stack run (step 1 above), fix anything the live stack surfaces
(reflecting changes into PHASE_2.md per governance), and prepare the AWS
showcase runbook for Arun's demo apply.
