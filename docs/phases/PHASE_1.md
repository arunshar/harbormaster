# Phase 1: Vertical slice (ultra-refined execution plan)

Status: APPROVED 2026-06-19, NOT STARTED. Do not begin execution until (a) the Ray/rate submission is done, (b) Arun has completed the AWS setup guide below, and (c) the internship-contents reveal has been folded in or explicitly deferred. Governance: this doc is the working plan for Phase 1; any change updates this file AND the master plan (~/.claude/plans/i-am-thinking-to-rustling-sifakis.md), and is re-confirmed before executing. No scope drift mid-phase.

## Local slice progress (no-AWS, zero-cost) - 2026-06-22

Built the parts of Phase 1 that need neither an AWS account nor any spend, so the
deterministic scoring logic is real and tested ahead of gate G0. All of the below
runs offline (`make serve-test`, 36 passed + 1 postgres test skipped; `ruff` clean).
A 5-dimension adversarial review (9 confirmed findings) was applied: all-segment
implausible-speed scoring, AGM-weighted gap severity, single-cause jump fixture,
asyncpg jsonb codec, 404 on unknown-trace feedback, and tests excluded from the wheel:

- 1.1 service + CI scaffold: DONE. `pyproject.toml` (ruff + pytest), `serving/app`
  package, recorded fixture `streaming/fixtures/ais_recorded.jsonl` (2709 events / 6 h,
  with a planted multi-hour gap, an implausible jump, and an off-corridor vessel) +
  `expectations.json` + recorded SHA256, schema-validating loader, and
  `.github/workflows/serving-ci.yml` (lint + unit + container build, no deploy).
- 1.2 GeoTrace serving adaptation: DONE (single-vessel). Vendored deterministic
  agents + prism kernel; `HeuristicPlanner` (routes by history 0/1/3+);
  `POST /v1/score-ais` + `orchestrator.run_plan` (no LLM); real Postgres HITL backend
  with an in-memory fallback; `/healthz` + Prometheus `/metrics`; the corridor add-on
  (`CorridorDeviationDetector` + `app/artifacts/corridors.json`, design in
  `docs/corridor-detector.md`). Golden checksums pass against `expectations.json`.
  RendezvousFinder/TGARD is vendored and unit-tested but not routed for single-vessel
  scoring (it activates in the future multi-vessel endpoint).
- 1.5 feature funcs as a local library: DONE. `streaming/features` (haversine,
  v_required, the `p_physical` cheap-gate) with a test asserting `v_max` equals the
  serving config exactly. The Flink job that deploys these (gate G5) needs AWS.

Pending on AWS (gate G0) / owner tasks, unchanged by this slice: 1.0 pre-flight,
1.3 Terraform modules (G3), 1.4 ingestor deploy (G4), 1.5 Flink deploy (G5), 1.6
Streamlit console (G6), 1.7 observability/SLOs (G7), 1.8 e2e acceptance (G8), 1.9
live toggle + teardown (G9). Preconditions (a) Ray/rate submission and (b) AWS setup
remain owner tasks; (c) the internship reveal is folded in via the corridor add-on.

## Goal
A genuinely production-grade vertical slice: recorded AIS replay -> Kinesis -> Managed Flink features + P_phys gate -> async score on the ECS Fargate GeoTrace front door (deterministic agents) -> anomaly to the Streamlit HITL console, every event landing in S3/Iceberg, with full observability and the $75 guardrails honored. Each sub-phase has a deliverable, reuse anchors, and a verification GATE (unit tests, a smoke test, and a checksum). Nothing proceeds past a red gate.

## Decisions locked for Phase 1
- Serving compute: ECS Fargate (GeoTrace container as-is, scale to zero, ~$5/mo). EKS deferred to Phase 5 (the EKS control plane alone is ~$73/mo and would eat the whole $75 cap).
- Region: us-east-1.
- AIS source: replay-first (recorded MarineCadastre fixture in S3); live AISStream.io added as a feature-flagged ingestor mode at 1.9.
- Live-scoring path strips GeoTrace's LLM planner: a deterministic HeuristicPlanner + a new POST /v1/score-ais endpoint run the existing deterministic agents (SpaceTimeReasoner, GapDetector / STAGD+AGM, RendezvousFinder / TGARD, Validator / S-KBM) with zero LLM cost.

## Prerequisite: AWS setup (one-time, before 1.0; region us-east-1)
> Scripted on-ramp: this prose is now an ordered runbook in `docs/AWS_SETUP.md`
> (+ `docs/AWS_SETUP.html`), with steps 2's role + state-bucket scaffolding scripted
> in `infra/aws/bootstrap.sh` (idempotent, `--dry-run`) and `terraform.tfvars`
> pre-filled. The steps below are the source of truth; the runbook orchestrates them.
1. Account hygiene: enable MFA on root, then stop using root; create an admin via IAM Identity Center (SSO) or an IAM admin user.
2. CLI: AWS CLI v2 configured; `aws sts get-caller-identity` succeeds in us-east-1.
3. Platform role: create the IAM role the finops budget action attaches the deny policy to and that Terraform/services assume (e.g. harbormaster-platform); record it as platform_role_name in terraform.tfvars.
4. Billing: enable Cost Explorer (~24h to populate); confirm budget-action and cost-anomaly permissions.
5. State bucket: manually create a dedicated, versioned, encrypted S3 bucket for Terraform state (NOT the data lake).
6. Phase 0 apply: cd infra/terraform/envs/base; cp terraform.tfvars.example terraform.tfvars; set project, aws_region=us-east-1, platform_role_name, alert_email; make fmt validate plan apply. Confirm budgets, the $75 IAM-deny action, the cost-anomaly monitor, and the teardown Lambda.
7. Backend migration: enable the S3 backend in backend.tf with the state bucket + the tf_state_lock_table output; terraform init -migrate-state.
8. Guardrail proof: simulate a small over-spend and confirm the IAM-deny action blocks new resource creation; run the teardown Lambda (DRY_RUN=true) and confirm the SNS cost summary.
Local prereqs: terraform >= 1.6, AWS CLI v2, docker, jq, python 3.11 for the container build; kubectl + helm later (Phase 5).

## Sub-phases and gates

1.0 Pre-flight (gate G0). AWS setup complete; Phase 0 applied; backend migrated; platform role present. Checksums: aws sts get-caller-identity ok in us-east-1; terraform plan shows no drift; the $75 budget action and teardown Lambda exist; Cost Explorer populated.

1.1 Service + CI scaffold (gate G1). Python 3.11 service project (pyproject, ruff, pytest); recorded MarineCadastre fixture streaming/fixtures/ais_recorded.jsonl (a few thousand events over ~6h, >=1 known implausible jump and >=1 known multi-hour AIS gap) + sidecar expectations.json naming the known-anomaly MMSIs and timestamps; GitHub Actions CI (lint + unit + container build, no deploy). Unit: fixture loader parses and schema-validates every record. Smoke: CI green. Checksum: fixture committed with a recorded SHA256 and expectations.json.

1.2 GeoTrace serving adaptation (gate G2). Reuse geotrace-agent: vendor the deterministic agents + prism kernel; add app/agents/heuristic_planner.py (deterministic routing by history length, no LLM); add AisScoreIn + POST /v1/score-ais; add orchestrator.run_plan(plan) skipping the planner; implement the real Postgres HITL backend (replace the in-memory _mem stub in observability/feedback.py) with a table (id, trace_id, mmsi, ts, score, reasons jsonb, confidence, label, reviewer, created_at); keep /healthz + Prometheus metrics mirroring MIRROR serving/metrics.py. Unit: HeuristicPlanner routing for history len 0/1/3+; /v1/score-ais happy path returns score + reasons + hitl_flag; the Validator S-KBM gate rejects an impossible region (422); HITL enqueue writes a row; confidence < 0.7 sets hitl_required. Smoke: docker build then run, curl /healthz == ok, POST /v1/score-ais on one fixture event returns a score in < 200 ms. Checksum (golden): the documented known-anomaly event yields hitl_required (or an anomaly reason) matching expectations.json within tolerance; a documented normal event yields none.
Corridor add-on (from the internship intake): also add a CorridorDeviationDetector as a third deterministic agent, using a static-corridor graph artifact (a frozen GTRA-style graph for the demo regions, built offline from NOAA ENC charts + a one-time MarineCadastre extract, loaded read-only at startup from the S3 model bucket). It runs the GTRA association test (perpendicular distance of each AIS point to the nearest sea-lane edge) and emits two reasons into the same fusion + HITL path: off_corridor (positional deviation from the nearest lane) and unexpected_node (a course change far from any waypoint node). Inline CPU, no new always-on cost. Unit: the perpendicular-distance association flags an off-corridor point and passes an on-corridor point. Checksum: a known off-corridor fixture event (added to expectations.json) is flagged off_corridor. Design + grounding in docs/internship/INTEGRATION.md.

1.3 Terraform Phase 1 modules (gate G3). Extend Phase 0 (name_prefix / tags / outputs conventions): modules/kinesis (1-shard ais-raw), modules/firehose (Kinesis -> S3 Iceberg ais_raw, partitioned by days(time_stamp), mmsi), modules/rds (Postgres 16 + PostGIS, db.t4g.micro free tier, private subnets, SG), modules/ecs_cluster (Fargate + Fargate Spot), modules/ecs_serving (serving task def + service + target-tracking autoscale 1->3, fronted by API Gateway HTTP API + VPC Link + Cloud Map service discovery, NOT a standing ALB), modules/ecs_ingestor (replay-ingestor task), modules/kda_flink (Managed Apache Flink app + IAM: read Kinesis, write DynamoDB + S3, call the serving endpoint). Reuse Phase 0 outputs: vpc_id, private_subnet_ids, lake_bucket_name, feast_online_table_name (the DynamoDB features table), budget_alerts_sns_topic_arn. Wire into envs/base + outputs + tfvars.example. Verification: terraform fmt -check, validate, plan clean; gate = apply in the demo env, then destroy. Checksum: plan shows the expected resource count, no replacement of Phase 0 resources, Project/Environment tags on every new resource.

1.4 Replay ingestor (gate G4). streaming/ingestor: a Fargate task that reads the fixture from S3 and PutRecords (batched, partitionKey=MMSI, ~10x real time) to Kinesis; dual-mode via env (REPLAY default; AISStream websocket with exponential backoff behind AIS_LIVE=true, wired at 1.9). Unit: replay reader yields records in time order; kinesis batching respects 500-record / 5 MB limits; backoff schedule. Smoke: run against demo Kinesis; GetRecords returns the fixture count. Checksum: records-in == fixture line count; no single hot shard.

1.5 Flink feature job (gate G5). streaming/flink: source Kinesis ais-raw, keyBy(MMSI), 1-min tumbling window, compute features (sog, cog, heading, gap_since_last_s, distance_m, v_required_mps, p_physical = min(1, v_max_mps / max(v_required, eps)), v_max from GT_VESSEL_V_MAX_KTS = 25 kts = 12.86 m/s), apply the P_phys cheap-gate (drop / low-priority below 0.3), sink features to the DynamoDB features table, async-IO POST /v1/score-ais to the serving endpoint (API Gateway HTTP API, or the Cloud Map internal DNS from in-VPC) for events passing the gate, Firehose-tee the enriched raw event to S3/Iceberg. Unit (feature funcs as a local library): haversine, v_required, the p_physical formula equals the config constant exactly, window aggregation. Smoke: deploy, push the fixture through, confirm features in DynamoDB, a returned score, events in Iceberg. Checksum: for the known-anomaly event, p_physical < gate and serving flags it; Iceberg row count == events passing the gate.

1.6 Streamlit HITL console (gate G6). serving/frontend (reuse the GeoTrace Streamlit): read the Postgres HITL queue, show enqueued anomalous/ambiguous events on a map with reasons, let a reviewer label {correct, incorrect, ambiguous} via POST /v1/feedback, write the verdict to Postgres. Smoke: open the console, see the known-anomaly event enqueued, label it, confirm the DB row updates. Checksum: a labeled verdict persists and is queryable (the seed of the Phase 4 RL-flywheel data).

1.7 Observability + SLOs (gate G7). Distributed tracing was a PLANNED gate target (OTel traces spanning ingestor -> Kinesis -> Flink -> serving into AWS X-Ray or CloudWatch) but was NOT implemented: no OpenTelemetry or X-Ray instrumentation exists in serving/ or streaming/, so the "one trace spans the whole pipeline" smoke below was not met and distributed tracing remains future work. What is built and gates this phase: Prometheus metrics scraped or via CloudWatch EMF; extend cost_tracker to a cost-per-inference number; a Phase 1 dashboard (availability, p95 score latency, anomalies/min, events/min, $/inference); Phase 1 SLOs (/score success 99.9% over the demo window; p95 < 300 ms kernel path; end-to-end replay-to-HITL p95 < 10 s). Smoke (metrics path): the dashboard populates; an injected error shows. Checksum: the dashboard reports a real $/inference and a real p95.

1.8 End-to-end Phase 1 acceptance test (gate G8, the phase gate). A scripted e2e test (tests/e2e/test_phase1.py + a make target) that brings up the demo env (terraform apply + ecs deploy + flink start), runs the replay ingestor over the fixture, then asserts: (a) the documented known anomaly is scored and visible in the Streamlit HITL / anomaly output within the ~10 s p95 SLO; (b) every fixture event is in Iceberg and queryable via Athena (count reconciles with fixture minus gate-dropped); (c) cost_tracker shows a real $/inference; (d) no error-level logs; (e) the slice tears down clean (terraform destroy leaves only the base). Checksums: known-anomaly MMSI present in output; Athena count reconciles; p95 within SLO; spend delta logged. This gate must be green to declare Phase 1 done.

1.9 Live AIS toggle + cost/teardown drill (gate G9). Enable AIS_LIVE=true (AISStream.io with reconnect/backoff; off by default; replay stays the test/CI path); FinOps reconciliation (month-to-date spend under budget, $/inference recorded); teardown drill (teardown Lambda DRY_RUN then wet; confirm scale-to-zero and base-only remains). Checksums: live mode scores events end-to-end for a short window; spend < the Phase 1 envelope; teardown verified.

## Cost envelope (us-east-1, $75 cap)
Kinesis 1 shard ~$11, Firehose ~$3-5, RDS t4g.micro free tier ~$0 (else ~$12), DynamoDB on-demand ~$1-3, S3/Athena ~$2, ECS Fargate serving ~$3-5, Managed Flink KPUs during demos ~$3-8/run, ALB ~$16/mo. WATCH: the ALB (~$16/mo always-on) and any always-on Flink are the two budget threats; run both in demo-mode by default, and consider exposing the service via API Gateway HTTP API or a public Fargate task instead of a standing ALB if the ALB cost bites. Steady always-on target ~$30-40/mo; bursts ~$5/demo.

## Reuse anchors (do not rebuild)
geotrace-agent app/agents/{space_time_reasoner,gap_detector,rendezvous_finder,validator}.py, app/components/space_time_prism.py, app/main.py routes, app/models.py (QueryOut), app/config.py (GT_VESSEL_V_MAX_KTS=25, GT_HITL_CONFIDENCE_THRESHOLD=0.7), observability/{feedback.py,cost_tracker.py}, app/Dockerfile (python:3.11-slim, port 8000, uvicorn); MIRROR serving/metrics.py (Prometheus shape) and serving/inference/app.py (score request/response contract); the Phase 0 Terraform module/output conventions.
