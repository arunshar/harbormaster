# Harbormaster

A production-grade maritime anomaly-detection platform on AWS. Harbormaster ingests live AIS vessel traffic (~150K ships, ~600 GB historical AIS), serves spatial anomaly detectors over a streaming feature plane, and trains heavy models off-cloud on MSI. Phase 0 builds the foundations and the FinOps cost guardrails before any spend.

> **HONEST FRAMING**
>
> ESRI (Summer 2023, a real company, a real team, real clients) shipped the original maritime detector plus the AWS MLOps around it. That work belongs to ESRI.
>
> Harbormaster is a clearly-labeled PERSONAL extension by Arun Sharma. It is never merged with ESRI code, data, or infrastructure, and it never claims ESRI's deliverables as personal work.
>
> What Harbormaster closes (real, demonstrable platform skills): change-data-capture (CDC), streaming, production distributed systems, MLOps, observability.
>
> What Harbormaster does NOT close: a sharded query router, and a consensus implementation. Those remain out of scope and are not claimed.
>
> Personas, customers, and case studies introduced in later phases are SIMULATED for demonstration and are labeled as such wherever they appear.

## Architecture summary: train on MSI, serve on AWS

Harbormaster splits into two planes:

- **Training plane (MSI, off-cloud):** heavy model training (for example the Pi-DPM diffusion model and the spatial detectors) runs on the University of Minnesota Supercomputing Institute (MSI) Slurm cluster. There is no GPU on AWS. Trained artifacts are exported and promoted into the serving plane.
- **Serving plane (AWS):** live AIS ingestion, streaming feature computation, low-latency inference, and the lakehouse all run on AWS. This is the plane Terraform provisions.

See `docs/ARCHITECTURE.md` for the full diagram and the opinionated tradeoffs.

## Repository layout

| Path | Purpose |
| --- | --- |
| `README.md` | This file: framing, architecture summary, phase status, quickstart. |
| `docs/HONESTY.md` | The locked honesty framing, real-vs-simulated labeling rules, gap talk-track. |
| `docs/ARCHITECTURE.md` | Hybrid architecture diagram and the key tradeoffs. |
| `docs/SYSTEM_DESIGN_DECISIONS.md` (+ `docs/system-design-decisions.html`) | Staff-level decision records: each component mapped to its canonical pattern and source (Fowler/Joshi, Kleppmann DDIA, Newman, Richardson, Nygard, Google SRE, HelloInterview), a SAGA deep-dive, AIS capacity sizing, and a 45-minute interview walkthrough. The HTML is an interactive learning companion. |
| `PLATFORM_WAR_STORIES.md` | Debugging war stories (P1-P28), most grounded in live runs; a handful still anticipated. |
| `docs/PLATFORM_BOOK.md` | Consolidated build record, reviews, and operations: one entry point across all five phase docs, the external audit, the runbooks, and the war-stories catalog. |
| `Makefile` | `fmt`, `validate`, `plan`, `apply`, `destroy` over `infra/terraform/envs/base`. |
| `.gitignore` | Terraform, Python, env, and OS ignores. |
| `infra/terraform/versions.tf` | Provider pinning (aws ~> 5.x, archive, random). |
| `infra/terraform/modules/network/` | VPC and networking foundation module. |
| `infra/terraform/modules/state_stores/` | S3 / DynamoDB state and data stores module. |
| `infra/terraform/modules/finops/` | Budgets, budget actions, SNS alerts, the $75 hard cap. |
| `infra/terraform/envs/base/` | The base environment that wires the modules together. |
| `infra/terraform/envs/demo/` | The demo environment (ephemeral, teardown-friendly). |
| `infra/lambda/teardown/` | Teardown Lambda invoked by the cost guardrail. |
| `deploy/helm/` | Kubernetes / EKS Helm charts (Phase 5, not yet built). |
| `streaming/flink/` | Flink streaming jobs (Phase 1, built and run live on AWS). |
| `cdc/` | Change-data-capture pipeline (Phase 2, local-stack accepted; AWS showcase not yet run). |
| `serving/` | Model serving and the inference front door (Phase 1, built and run live on AWS). |
| `lake/` | EMR Spark backfill + Iceberg lake + training-set export (Phase 3, built and run live on AWS). |
| `mlops/` | Model registry, promotion pipeline, drift/HITL/preference flywheel (Phases 3-4). |
| `fde/` | Forward-deployed-engineer simulated case studies (Phase 5, not yet built). |

## Phase status

The scopes below reflect the master plan's real phase structure (this table
originally predated it); per-phase detail lives in `docs/phases/`.

| Phase | Scope | Status |
| --- | --- | --- |
| Phase 0 | Foundations: networking, state stores, FinOps guardrails, $75 hard cap. | Deployed (live in AWS since 2026-07-03) |
| Phase 1 | Streaming + serving vertical slice: ingestor, Kinesis, Flink features, ECS front door, HITL console, observability. | AWS showcase run live 2026-07-04: a real planted anomaly reached the HITL queue end to end |
| Phase 2 | CDC: Postgres -> Debezium -> Kafka -> online store, slot-lag monitoring. | Local stack accepted (e2e 5/5, 0.57s smoke); AWS MSK showcase not yet run |
| Phase 3 | Lake + promotion: EMR backfill -> Iceberg, Feast export, SageMaker async Pi-DPM endpoint, holdout/shadow/canary promotion. | AWS showcase run live 2026-07-04 (EMR backfill, SageMaker scale-to-zero both directions, live promotion pipeline); torn down clean |
| Phase 4 | Drift -> HITL -> RL flywheel: drift taxonomy, preference triples, reward-hacking probe. | Code-complete (gates 4.0-4.7, `phase4-flywheel`, local-plane only); adversarially reviewed |
| Phase 5 | Multi-tenant + scale: EKS/KEDA, tenant isolation, FDE case studies, explanation layer. | Planned and signed off (`docs/phases/PHASE_5.md`); build is a later sprint |

## Phase 0 quickstart

```bash
cd infra/terraform/envs/base
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: set aws account id, region, platform_role_name, alert_email
make fmt validate plan
```

Nothing in this repository is applied to any AWS account by the scaffolding itself. The Terraform is parameterized infrastructure-as-code that you apply later, against your own account, after reviewing the plan.

## Cost guardrails

Harbormaster builds guardrails before any spend.

- **Hard cap: $75/month.** An `aws_budgets_budget_action` attaches an IAM deny policy to `var.platform_role_name` when the $75 monthly budget is breached, cutting off the platform role's ability to create new spend.
- **Soft budget: $30/month.** A separate budget sends SNS email alerts at $5, $15, and $25 of actual spend, plus a forecast alert at $30.
- **Provider pinning is mandatory.** `aws ~> 5.x`, `archive`, and `random` are pinned in `infra/terraform/versions.tf`. War story P8 is about provider drift forcing resource replacement, so pinning is a hard requirement, not a preference.

## Disclaimer

Harbormaster is a personal engineering project. Any personas, customers, deployments, or case studies that appear in later phases are simulated for demonstration purposes and are labeled as simulated wherever they appear. Nothing here represents ESRI work, ESRI data, or ESRI clients.
