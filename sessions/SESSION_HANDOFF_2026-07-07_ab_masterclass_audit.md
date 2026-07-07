# Session handoff: AB System Design Masterclass audit + remediation (2026-07-07)

One-line status: audited Harbormaster against Arpit Bhayani's System Design
Masterclass, closed every local gap, got CI green, threaded the deferred IAM
boundary, wrote the apply runbooks, and merged it all to `master`. The only thing
left is the live AWS apply, which is deferred to a dedicated window (Arun-run).

## What this session did

Started from the request: cross-check the whole platform against the masterclass
best practices and bring it to a principal-engineer / international-buyer bar.
Chosen scope: "both, phased" (local no-spend credibility + correctness first, then
production-guarantee hardening flagged separately).

Delivered as one branch `feat/ab-masterclass-audit`, now merged to `master`:
- Phase 0 (`1a09f14`): `docs/AB_MASTERCLASS_AUDIT.md` (16-dimension gap matrix with
  a run-vs-documented column and honesty scoping), four ADRs in `docs/adr/`,
  two doc-drift fixes (Bedrock relabeled Phase-5-planned, OTel/X-Ray relabeled
  not-built), war stories P1-P8 tagged ANTICIPATED.
- Phase 1 code (`5cb5a01`): Kinesis exponential backoff, watchlist single-flight
  coalescing, Flink pure-logic extraction to `streaming/flink/window_logic.py`
  (cloudpickle by-value preserved), RDS cdc_slot_lag cert fix (removed CERT_NONE).
- Phase 1 gates (`5439d7b`): pre-commit + bandit + coverage ratchet (78.6%),
  `iac-ci` (terraform fmt/validate + tflint + checkov baseline), and a local
  M4 Pro scoring benchmark under `bench/` (p95 ~0.58 ms, ~1787 scores/sec/core).
- Phase 2A (`69b8d1a`): `serving/app/burn_rate.py` Google-SRE multi-window
  burn-rate wired into `slo.py` + `mlops/promote.py` (closes DR-13); Iceberg
  upsert idempotency + partition spec + compaction; streaming DLQ + scorer retry;
  hermetic 2-partition CDC rebalance proof.
- Phase 2B authored (`45d221c`): IAM permissions-boundary + resource scoping
  (closes the iam:* on Resource-* escalation); apigw authorizer + throttling +
  access logging + gated WAF.
- Closeout (`0f59a11`): refreshed audit statuses; war stories P29-P33.
- CI fixes (`1943db9`, `9a75eab`): pyiceberg into the [lake] extra; regenerated
  the checkov baseline against the CI-view tree (see P34).
- IAM boundary threading (`5d11d42`): optional `permissions_boundary_arn` var on
  all 12 modules + 19 roles; `envs/base` derives the ARN and passes it to all 12
  calls; count-gated so the default plan is unchanged, footgun-free.
- War story P34 (`349b19f`) and the apply runbooks (`86e0db1`, `ffc8a20`).

Full suite 434 passed / 9 skipped. All five CI checks green.

## Current state (as of merge)

- PR #2 MERGED into `master`, merge commit `5e48fd7`. PR #1 (phase4-flywheel)
  auto-marked MERGED as a superset once #2 landed. Local `master` fast-forwarded.
- `master` now contains phases 0-4, the audit, the CI fixes, the boundary
  threading, and both runbooks.

## The ONE open item (deferred, Arun-run, do NOT run unattended)

Apply the IAM boundary + API Gateway hardening in a dedicated AWS window. Full
steps: `docs/runbooks/MERGE_AND_APPLY.md` (Part 2) and `docs/runbooks/IAM_BOUNDARY_APPLY.md`.
Shape: Part A free/standing deploy-identity hardening via `bootstrap.sh` (creates
the boundary policy, reconciles the platform role's inline policy); Part B billable
Phase 1 window for the module-role boundaries + apigw, applied as `arun-admin` (not
boundary-gated, sidesteps lock-out), torn down after; Part C optional switch to the
platform role. CMK is NOT authored (no aws_kms_key anywhere), so it needs code
first, out of scope. Claude declined to run this unattended (live-cloud real-money
IAM mutation + P32 sequencing risk + teardown discipline; terraform apply is also
historically blocked by the harness auto-mode classifier). Arun chose to HOLD it
until his window (pause-and-focus posture).

## Tooling notes worth keeping

- Explore/Plan subagent types are broken this session (hard-routed to an
  unavailable glm-5.2, fail at 0 tokens). The Workflow tool works (its agents
  inherit the session Opus model); used it for all fan-out. The Agent-tool model
  override does not fix Explore.
- checkov baseline is coupled to local state (war story P34): the gitignored
  `envs/base/terraform.tfvars` (enable_phase1=true) makes local checkov emit
  [0]-indexed module addresses CI cannot reproduce. Regenerate the baseline from
  a `git archive HEAD infra/terraform` tree (no tfvars, no .terraform) and pin
  checkov to the baseline-generating version.

## Resume prompt (paste into a fresh session in a week or two)

> Resume the Harbormaster AB-masterclass audit session. Read memory
> project_harbormaster.md (the UPDATE 2026-07-07 block) and this file
> (sessions/SESSION_HANDOFF_2026-07-07_ab_masterclass_audit.md) first. State: the
> audit + remediation branch is MERGED to master (merge commit 5e48fd7); CI is
> green; the IAM boundary is threaded through all 12 modules. The ONLY open item
> is the live AWS apply of the IAM boundary + apigw hardening, deferred to a
> dedicated window and Arun-run, per docs/runbooks/MERGE_AND_APPLY.md +
> docs/runbooks/IAM_BOUNDARY_APPLY.md. Do NOT run any terraform apply or
> bootstrap.sh mutation unattended. If I say I am at the terminal in an AWS
> window, drive the apply live: issue each command, I confirm the plan and
> outputs, we verify every harbormaster-base-* role shows the boundary ARN and the
> apigw front door rejects unsigned requests, then we tear down (enable_phase1
> false + make apply). Honor the pause-and-focus posture: default to closing out,
> do not propose new project scope. CMK is not authored (offer to author a
> modules/kms only if I ask).

## Guardrails (carried)

No em dashes. Commits authored Arun Sharma, no Claude co-author. terraform apply
and any bootstrap.sh IAM mutation are Arun-run in a dedicated window, never
unattended. $75 FinOps cap + teardown-after discipline. Keep work off iCloud.
