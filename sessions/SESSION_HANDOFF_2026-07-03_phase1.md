# Harbormaster session handoff — 2026-07-03 (Phase 1 complete)

## One-line state
Phase 0 (FinOps guardrails + network + state stores) is DEPLOYED to AWS, and Phase 1
(the streaming + serving vertical slice) is CODE-COMPLETE across gates 1.1-1.9, all
committed and pushed on branch `phase1-aws-gates` (HEAD `7e6fd1a`). Gate 1.3 infra was
proven end to end (apply 40 resources, destroy 40, zero Phase 0 disturbance). Whatever
is left for Phase 1 is deploy-only. The next build phase is **Phase 2 (CDC pipeline)**,
the resume-critical gap-closer.

## Environment / access (verified this session)
- Repo: `~/code/harbormaster` ONLY (never the `~/Desktop/harbormaster` iCloud copy).
  GitHub `arunshar/harbormaster` (PRIVATE). Active branch `phase1-aws-gates`.
- AWS account `645322802947`, region **us-east-1** (the CLI default is us-west-2/Oregon
  but ALL infra is us-east-1; pass `--region us-east-1` for ad-hoc CLI).
- Off root: CLI = IAM user **`arun-admin`** (AdministratorAccess + MFA); root access keys
  deleted; root MFA on.
- Terraform state in S3: `harbormaster-tfstate-645322802947/base/terraform.tfstate`,
  DynamoDB lock `harbormaster-base-tf-state-lock`. Backend already migrated.
- $75/mo hard cap LIVE (Budget action attaches an IAM deny to the `harbormaster-platform`
  role on breach). Alerts CONFIRMED to **arunshar@umn.edu** (the gmail arun08sharma@gmail.com
  is undeliverable for AWS SNS - do not use it).
- Local tooling: aws-cli 2.35, terraform 1.15.6, docker, jq, python 3.12 venv at `.venv`.

## Guardrails / conventions (do not drift)
- No Claude co-author / no "Generated with" footer on commits. No em dashes in any output.
  Paste-ready content in fenced code blocks. Act autonomously, minimize prompts.
- Work only from `~/code` (never iCloud / Dropbox - cloud sync evicts git worktrees).
- **`terraform apply` is BLOCKED for Claude** by the auto-mode classifier (protected
  IAM/networking). Arun runs applies interactively; Claude does `plan` + file edits + tests.
- Everything Phase 1 is gated behind `enable_phase1` (default false) in
  `infra/terraform/envs/base/terraform.tfvars`, so a normal `make apply` stays Phase-0-only.

## What Phase 1 delivered (9 commits on phase1-aws-gates)
- **1.1 / 1.2** (branch `phase1-serving-slice`): local serving slice - deterministic scorer
  (STAGD / TGARD / S-KBM + CorridorDeviationDetector), HeuristicPlanner (no LLM),
  `POST /v1/score-ais`, real Postgres HITL backend, `POST /v1/feedback`,
  `GET /v1/hitl/pending`, `/healthz`, `/metrics`.
- **1.3** (`f672d8b`, `8bd0fc7`, `b77e6ab`): 8 Terraform modules - `kinesis`, `firehose`
  (-> S3 lake `raw/`), `rds` (Postgres 16 t4g.micro, RDS-managed Secrets Manager secret,
  private), `ecs_cluster` (Fargate + Spot), `ecs_serving` (ECR + Cloud Map + IAM + CPU
  autoscale 1->3; public subnets + public IP for egress with the SG locked to the VPC CIDR),
  `apigw` (API Gateway HTTP API + VPC Link + Cloud Map, NO standing ALB), `ecs_ingestor`,
  `kda_flink` (app gated behind `flink_code_s3_key`). Wired into `envs/base` behind
  `enable_phase1`. PROVEN: apply 40 / destroy 40 clean.
- **1.4** (`dd679b4`): `streaming/ingestor` - replay ingestor (fixture from S3/local via
  `replay.loader` -> Kinesis, batched to the 500-record/5MB limits, partitionKey=MMSI,
  ~10x pacing) + `Dockerfile` + 8 tests.
- **1.5** (`279d823`): `streaming/flink` - `transforms.py` (pure) + `job.py` (KDA PyFlink
  pipeline: Kinesis -> keyBy MMSI -> keyed prev-fix state -> `features.window_features` ->
  P_phys gate -> DynamoDB put + async score POST) + `make flink-package` -> `dist/flink-app.zip`
  + 7 tests.
- **1.6** (`3a2650f`): `serving/frontend` - Streamlit HITL console + pure `hitl_client.py`
  (reads `/v1/hitl/pending`, posts `/v1/feedback`) + 6 tests.
- **1.7** (`c4ac5e6`): `serving/app/slo.py` (Phase 1 SLOs + evaluator) + Terraform
  `observability` module (CloudWatch dashboard + 2 SLO alarms on API-GW/ECS/Kinesis) + 4 tests.
  `plan enable_phase1=true` = 43 to add.
- **1.8** (`7e6fd1a`): `tests/e2e/test_phase1.py` (skip-guarded by `HM_E2E`) + pure helpers
  + `make e2e` + 5 tests.
- **1.9** (`7fd2432`): `streaming/ingestor/live.py` (AISStream.io websocket, `AIS_LIVE`
  toggle, reconnect with capped backoff) + 6 tests.
- Full suite: **72 passed / 3 skipped** (2 e2e + 1 postgres), ruff clean.

## Phase 1 deploy-only remaining (Arun-run, demo-apply-time)
1. Set `enable_phase1 = true` in `terraform.tfvars`; `make plan` then `make apply` (~43 resources).
2. Build + push the serving & ingestor images to their ECR repos (`serving/Dockerfile`,
   `streaming/ingestor/Dockerfile`).
3. `make flink-package`; upload `dist/flink-app.zip` to the models bucket; set
   `flink_code_s3_key` (kda_flink var) so the Flink app is created.
4. Run the ingestor task over the fixture; then `make e2e` with `HM_E2E=1` and
   `SERVING_URL=$(terraform -chdir=infra/terraform/envs/base output -raw serving_api_endpoint)`.
5. Teardown: set `enable_phase1 = false`; `make apply` (destroys Phase 1, keeps Phase 0).
   NEVER `make destroy` (that would take Phase 0 with it).

## Phase 2 = CDC pipeline (NEXT; the resume-critical gap-closer)
From the master plan `~/.claude/plans/i-am-thinking-to-rustling-sifakis.md` (Phase 2, ~lines
105-107, 190):
- RDS Postgres 16 with `wal_level=logical` (pgoutput); tables `vessels` / `watchlist` /
  `sanctions_flags`, edited via the Streamlit console.
- Debezium on Kafka Connect (Strimzi in-cluster default; MSK Serverless showcase on demand)
  -> an idempotent, LSN-guarded consumer -> Feast/DynamoDB + Redis (invalidate on change) +
  Iceberg `cdc_audit`.
- Exactly-once = at-least-once transport + idempotent sink: upsert keyed by PK, monotonic
  `last_applied_lsn` guard, offset-commit-after-sink-ack, tombstone -> delete, snapshot->stream
  duplicate-safe.
- Acceptance: analyst flags a vessel in Streamlit -> within ~5 s serving scores it watchlisted;
  replay the CDC topic -> no duplicate online state; Debezium restart -> no lost change; delete
  -> removed from the online watchlist; `pg_replication_slots` lag alerting.
- War stories to capture: **P1** replication-slot bloat (a stalled consumer pins WAL -> disk
  fills); **P2** duplicate AIS after consumer restart (non-idempotent sink).
- New repo dir **`cdc/`**. Closes the CDC gap; after Phase 2 ships, update
  `temporal-interview-prep/references/supabase-multigres-cover-note.md` (CDC now built; query
  router + consensus remain honest gaps).
- Governance (same as Phase 1): author `docs/phases/PHASE_2.md` (ultra-detailed, gates + unit
  tests + smoke + checksums) BEFORE execution; update the master plan and the phase doc on any
  change; no mid-phase scope drift. Gate all Phase 2 infra behind an `enable_phase2` toggle
  like Phase 1, so applies stay opt-in and cheap. Do NOT re-implement query routing or consensus
  (that is Vitess/Multigres territory; Harbormaster consumes Postgres).

## Key commands
- `make serve-test` (full suite) / `make serve-lint` (ruff over serving + streaming + tests).
- `make validate` (isolated, no creds) / `make plan` / `make apply` / `make flink-package` / `make e2e`.
- Phase 1 plan: `terraform -chdir=infra/terraform/envs/base plan -var enable_phase1=true`.

## Resume prompt for Phase 2
See the fenced prompt delivered in chat on 2026-07-03, or reconstruct from the "Phase 2" section
above. In short: load memory + the `arun-session-handoff` skill + this file + the master plan,
confirm the state and guardrails, then author `docs/phases/PHASE_2.md` and start the CDC build
gated behind `enable_phase2`, following the Phase 1 pattern (pure testable code + tests, Terraform
modules behind a toggle, commit per gate, plan/validate not apply).
