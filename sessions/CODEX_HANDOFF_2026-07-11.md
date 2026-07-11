# Codex handoff (2026-07-11)

Read this file in full before touching anything. It is the single, self-contained,
verified-today state of the Harbormaster repo, written so a fresh Codex CLI session
with no prior context can resume work correctly. Everything in it was independently
re-verified on 2026-07-10/11 (test run, coverage run, ruff/mypy/bandit run, grep
sweeps, git/gh state) rather than copied from older docs, and it corrects a couple
of small inaccuracies those older docs still had as of this writing.

## One-line status

Harbormaster (maritime AIS anomaly-detection platform, streaming + CDC + lakehouse
+ ML serving on AWS, training on MSI) passed a full System Design Masterclass audit
and remediation. `master` is clean, CI is green, 434 tests pass. The single
highest-priority open item is a live AWS `terraform apply` of an already-authored
IAM permissions-boundary and API Gateway hardening, deferred to a dedicated,
human-run window. Beyond that, the open items are real feature/scope gaps (Phase 5
multi-tenancy, a CMK, a two-variant live canary, an MSK live run), not bugs.

## Repo facts

- Path: `~/code/harbormaster`. Remote: `https://github.com/arunshar/harbormaster.git`.
- Branch: `master`, clean, synced with `origin/master`, HEAD `759fcc8`.
- Both PRs (#1 phase4-flywheel, #2 feat/ab-masterclass-audit) are MERGED. No open PRs.
- Test command: `make serve-test` (runs `.venv/bin/python -m pytest -q`). There is no
  `make test` target; do not invent one. Lint: `make serve-lint` (ruff on
  `serving streaming cdc lake tests`).
- Result today: **434 passed, 9 skipped**, coverage **79.41%** (floor `fail_under=75`
  in `pyproject.toml`, ratchet target 90% on new/changed modules). All 9 skips are
  environment-gated, not broken tests: 2 need `HM_TEST_PG_DSN` (a live Postgres),
  7 need `HM_E2E=1` or `HM_CDC_E2E=1` (a live AWS/CDC stack).
- `ruff check`, `ruff format --check`, and `bandit -c pyproject.toml -r serving
  streaming cdc lake mlops` are all clean today (0 findings; 13 pre-approved
  `# nosec` suppressions).
- `mypy` is **informational only**, not a CI gate: `.pre-commit-config.yaml` runs it
  at `stages: [manual]`, and neither GitHub Actions workflow invokes it. Running it
  today gives 72 errors in 27 files, dominated by missing third-party stubs (boto3,
  asyncpg, shapely, cloudpickle, pyflink, the MSK IAM SASL signer), plus a handful
  of real findings in `serving/app/pidpm_client.py` and two test files. Not a gate
  to fix before anything else; fix incidentally if you're already in one of those
  files.
- CI: two workflows, `serving-ci` (pytest+coverage+ruff+bandit) and `iac-ci`
  (terraform fmt/validate + tflint + checkov). Both green on the last 5 runs,
  including the two most recent post-merge runs on `master`.
- Makefile has no `plan`/`apply`/`destroy` shortcuts beyond the literal Terraform
  wrapper targets (`make plan`, `make apply`, `make destroy`, all against
  `infra/terraform/envs/base`, `COST_CAP := 75`); `make cost` prints the budget
  reminder. Full target list: `help cost fmt init validate plan apply destroy
  serve-install serve-lint serve-test serve-run serve-fixture serve-docker
  flink-jar flink-package e2e cdc-up cdc-down cdc-smoke cdc-consumer
  cdc-lambda-package cdc-e2e lake-quality-smoke lake-backfill-smoke
  lake-training-export-smoke lake-e2e pidpm-demo-checkpoint lake-package
  lake-package-venv drift-smoke drift-lambda-package drill-l3-drift-classification
  drill-l4-reward-hacking phase4-e2e`.

## What is built and verified (condensed: see the linked docs for depth)

- Full detail lives in `docs/AB_MASTERCLASS_AUDIT.md` (the 16-dimension D1-D16
  matrix, run-vs-documented status per dimension), `docs/PLATFORM_BOOK.md`
  (consolidated build narrative), and `PLATFORM_WAR_STORIES.md` (P1-P34, tagged
  ANTICIPATED vs GROUNDED). Do not duplicate those here; read them for depth on any
  specific dimension.
- Net: the CDC plane is production-shaped (real Postgres logical replication,
  LSN-guarded idempotent sink, hermetic 2-partition rebalance proof). Pure logic
  across lake, serving, and MLOps is densely tested. Lakehouse compaction/
  idempotency, streaming DLQ + scorer retry, a Google-SRE multi-window burn-rate
  auto-rollback signal (`serving/app/burn_rate.py`, wired into
  `mlops/promote.py:make_burn_check`), cache-stampede single-flight coalescing, and
  real CI/pre-commit/coverage/IaC-lint gates all landed and are tested.
  IAM least-privilege (permissions boundary + resource-scoped policy) and API
  Gateway hardening (SigV4 authorizer, throttling, access logging, gated WAF) are
  authored in Terraform and code-complete, not yet applied to AWS.
- Terraform standing state today: **only Phase 0 is live in AWS** (VPC, 2 S3
  buckets, 2 DynamoDB tables, FinOps budgets/SNS/teardown Lambda, base IAM roles).
  The gitignored local `terraform.tfvars` currently has `enable_phase1 = true`, so
  the *next* `terraform apply` from this machine would materialize the Phase 1
  streaming/serving plane; confirm intent before running `make apply` for any
  reason, and always run `make plan` first and read it.

## THE single deferred item: apply the IAM boundary + API Gateway hardening

This is the one item explicitly carried forward from the prior session as
Arun-run-only. Do not run any part of this unattended; treat it as requiring an
explicit "I am at the terminal in an AWS window, go" from Arun before issuing any
AWS-mutating command.

- **AWS account:** `645322802947`. **Region:** `us-east-1`.
- **Identities:** `arun-admin` (IAM user, AdministratorAccess, MFA, break-glass;
  apply as this identity, since it is NOT boundary-gated, which sidesteps the
  lock-out risk described below) and `harbormaster-platform` (the scoped deploy
  role and the target of the $75 hard-budget deny action).
- **The risk to respect (war story P32, `PLATFORM_WAR_STORIES.md:400`):** the
  permissions-boundary is a two-sided contract. A boundary-gated deploy identity
  can be denied `iam:CreateRole` for any role that does not carry the boundary.
  Applying as `arun-admin` avoids this entirely; do not switch the deploy identity
  to `harbormaster-platform` except as the optional, later, deliberate Part C below.
- **Runbooks (read both before doing anything):** `docs/runbooks/MERGE_AND_APPLY.md`
  (condensed walkthrough) and `docs/runbooks/IAM_BOUNDARY_APPLY.md` (full detail,
  verification commands, and rollback per part).
- **Part A (free, standing, do first):** `bash infra/aws/bootstrap.sh --dry-run`,
  read the plan, then `bash infra/aws/bootstrap.sh` for real. This creates the
  `harbormaster-permissions-boundary` customer-managed policy and reconciles the
  existing `harbormaster-platform` role's inline policy to the boundary-gated
  version (the script's Step 2 was fixed this session to reconcile an existing role
  instead of silently leaving its old, unscoped inline policy in place: grep
  `infra/aws/bootstrap.sh` for "reconciling its managed" to confirm the fix is
  present before relying on it).
- **Part B (billable Phase 1 window, apply as `arun-admin`):** `enable_phase1 =
  true` in `envs/base/terraform.tfvars` (it already is, per the state above),
  `make plan` and read the diff (confirm every `aws_iam_role` shows a
  `permissions_boundary` and the apigw stage shows the authorizer/throttling/
  access-log settings), `make apply`. Verify live: every `harbormaster-base-*` IAM
  role shows the boundary ARN
  (`arn:aws:iam::645322802947:policy/harbormaster-permissions-boundary`); a curl to
  the API Gateway stage without SigV4 signing is rejected. Then teardown:
  `enable_phase1 = false` and `make apply` (never `make destroy` on the base
  environment) to return to the ~$0 Phase-0-only standing state. The boundary
  policy and hardened platform role from Part A are free and stay.
- **Part C (optional, later, not required):** switch the deploy identity from
  `arun-admin` to the boundary-gated `harbormaster-platform` role and re-apply, to
  prove least-privilege empirically (this is DR-7's IAM half; see the ranked list
  below for DR-7's other, unrelated half). Keep `arun-admin`'s AdministratorAccess
  until this is proven.
- **CMK is explicitly out of scope for this apply.** No `aws_kms_key` resource and
  no `modules/kms` exist anywhere in the repo. If a customer-managed key is wanted,
  it needs to be authored first (a KMS module + wiring S3/RDS/DynamoDB/logs to it
  behind an `enable_cmk` flag), as its own separate piece of work, before any apply
  can include it.
- **FinOps guardrail while doing this:** hard cap $75/month (a budget action denies
  new spend on the platform role at breach), soft cap $30/month (SNS alerts at
  $5/$15/$25 actual, $30 forecasted). Known real limitation (war story P7,
  `PLATFORM_WAR_STORIES.md:103`): the hard-cap deny blocks *new* resource creation
  only, it does not stop resources already running; the nightly teardown Lambda is
  the actual backstop for that. MSK left running is the single biggest budget risk
  at ~$18/day if Phase 2 is ever applied; not part of this Part A/B/C sequence.

## Ranked list of everything else genuinely open

Ordered by what most changes the platform's real capability. Items 6 and the DR-3/
DR-4 ADR-backed ceilings are deliberate scope boundaries, not gaps: do not "fix"
them without a real requirement forcing it.

1. **Phase 5 multi-tenant isolation (DR-7's tenancy half): zero code.** No
   `tenant_id` appears anywhere in the repo (verified by grep across all `.py` and
   `.tf` files). Only a signed-off plan exists at `docs/phases/PHASE_5.md` (row-level
   security via `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`, a `Settings.tenant_id`
   default-deny). `deploy/helm/` and `fde/` are both empty placeholder READMEs
   waiting on this phase. This also blocks per-tenant SLO tiers under DR-13.
2. **Customer-managed KMS key: zero code.** No `aws_kms_key`, no `modules/kms`,
   anywhere. Current encryption is default SSE (S3 SSE-AES256, RDS
   `storage_encrypted`, DynamoDB PITR) plus AWS-managed keys (e.g. Kinesis uses
   `alias/aws/kinesis`, not a CMK). Needs to be authored as its own module before it
   can be part of any apply.
3. **Two-variant live SageMaker canary never wired.**
   `mlops/promote.py`'s `set_canary_weight` still targets a single-variant
   endpoint. This means DR-3's canary ramp is traffic-inert today, and DR-13's
   burn-rate auto-rollback (the calculator itself is real, tested code, mutation-
   tested per war story P33) has nothing live to actually gate yet. Needs a real
   two-variant SageMaker endpoint apply plus wiring `set_canary_weight` to it.
4. **Phase 2's AWS MSK Serverless showcase has never run against real AWS.** The
   local kind/Strimzi CDC stack passes 5/5 e2e; the managed-broker path is
   documented and Terraform-authored but has never been exercised live. This is the
   single clearest gap between what the docs describe and what has actually
   executed against real AWS.
5. **17 of 19 external HM3-AUDIT findings on the SageMaker/Terraform code remain
   unactioned** (only #01 and #02 are fixed and live-verified). The three flagged as
   mattering most if this endpoint ever serves a real checkpoint: #03 (no SNS
   failure-path notification), #04 (no `InvocationTimeoutSeconds`/`InferenceId` on
   invoke), #07 (no CloudWatch alarm for invocation errors/latency). Full 19-item
   list with IDs and rationale is in `docs/PLATFORM_BOOK.md` section 11's findings
   table.
6. **Real event-time windowing/checkpointing for the streaming plane is
   deliberately deferred**, not a bug: `docs/adr/0001-streaming-per-event-realization.md`
   states this explicitly and gives the revisit trigger ("only if late-fix
   correctness becomes a hard requirement"). Leave alone unless that trigger fires.
7. **One real code TODO:** `mlops/drift_decision.py:25-28` has
   `DISAGREEMENT_ALERT_RATE_PLACEHOLDER = 0.2`, a named placeholder threshold
   pending a real accumulated HITL disagreement-rate baseline from actual Phase 4
   execution (`TODO(real-phase-4-execution)`). Do not silently change the number;
   it needs real accumulated data behind it first.
8. **Structural, low-priority debt:**
   - `infra/lambda/` is excluded from CI's ruff-check target list entirely (both
     workflows only scope `serving streaming cdc lake mlops tests scripts`).
     Nothing in `infra/lambda/` is lint-gated today. (Re-verified 2026-07-10:
     `infra/lambda/drift_watch/test_handler.py` itself currently passes `ruff
     check` clean; an older doc claim that it fails is stale, most likely fixed by
     commit `139cf8d` after that doc section was written. The structural gap, not
     the specific failure, is what's real.)
   - No committed `terraform plan` output artifact anywhere backs the numeric
     plan-count claims ("0 add", "8 to add", etc.) scattered through the phase
     docs, unlike every other gate's checksums, which are pinned to a fixtures
     file.
   - The demo ECR repository `hm-pidpm-demo` from an earlier showcase window has
     not been deleted. Costs nothing idle; close it if it will not be reused.
   - `tflint` reports 48 pre-existing warning-level findings (missing version
     constraints, unused declarations), intentionally non-blocking
     (`.github/workflows/iac-ci.yml` comment: "burn down over time, then raise to
     warning"). `checkov`'s baseline currently suppresses 46 resource-level
     findings across 17 files; the baseline itself is fragile and coupled to a
     `git archive HEAD infra/terraform` tree per war story P34: regenerate it only
     from that exact tree, never with a local `terraform.tfvars` present, or the
     module-index addresses will not match what CI resolves.
   - Modules genuinely declared-but-not-locally-exercised (matches the repo's own
     `pyproject.toml` comments, not a coverage bug to chase): `lake/offline_store.py`
     (Feast `AthenaOfflineStore`, needs live Athena), `lake/backfill/job.py` (PySpark
     EMR entrypoint, needs a JVM this dev machine does not have),
     `serving/frontend/console.py` (Streamlit HITL console, no pytest harness for
     Streamlit UIs), `mlops/pidpm_container/server.py` (the real Pi-DPM container,
     needs an un-vendored pi-grpo scorer from a separate repo),
     `streaming/replay/generate.py` (a fixture-generation script).

Permanent, deliberate scope boundaries, not gaps to close: no consensus/quorum
or sharded query router (ADR 0004, permanent per `docs/HONESTY.md`), no real
multi-region DR (ADR 0003, RPO/RTO documented, single-region is the accepted cost
posture), Bedrock explanation layer and the EKS-hosted front door (both
Phase 5 plan items, not current build; Phase 1's actual, built serving compute is
ECS Fargate, and `docs/ARCHITECTURE.md` was corrected in this same commit to stop
saying EKS).

## Doc-accuracy fixes made in this same commit (so you don't re-find these)

- `docs/ARCHITECTURE.md` said the serving front door was "EKS-hosted." It is ECS
  Fargate today (EKS is the Phase 5 plan). Fixed the diagram and prose.
- `docs/AB_MASTERCLASS_AUDIT.md` phrased the CMK gap as "authored, none applied,"
  implying KMS code exists and just needs an apply. It does not exist at all.
  Reworded to say so, matching the runbooks' correct phrasing.

## Guardrails to carry forward

- Never run `terraform apply`, `terraform destroy`, or `bash infra/aws/bootstrap.sh`
  (for real, not `--dry-run`) without an explicit, in-the-moment go-ahead from Arun
  that he is at a terminal watching it happen. This applies to every part of the
  AWS-apply item above.
- `arun-admin` is the deploy identity for any apply (not boundary-gated, avoids
  P32). Never remove its AdministratorAccess until a `harbormaster-platform`-role
  apply is separately proven (Part C).
- $75/month hard cap, $30/month soft cap. Tear down anything applied for a
  demonstration in the same session (`enable_phaseN = false` + `make apply`, never
  `make destroy` on `envs/base`).
- No CMK without authoring it first, as its own reviewed piece of work.
- Commits: author "Arun Sharma", no AI co-author trailer of any kind, no em dashes
  in commit messages or docs, no fabricated numbers or claims not backed by an
  actual run with a cited artifact path (the project's standing honesty rail; see
  `docs/HONESTY.md`).
- Full test suite (`make serve-test`) green before and after any change; new logic
  gets new tests in the same change, 90% line+branch coverage on new/changed
  modules even though the repo-wide floor is 75%.
- Read `docs/HONESTY.md` before writing anything for external consumption (a
  portfolio page, an interview doc): it defines the real-vs-simulated labeling
  rules this repo follows and the FDE case studies in `fde/` must follow when built.

## Suggested first move

Do not start writing code immediately. Run `make serve-test` yourself first to
reconfirm the 434/9 baseline on your machine, then pick one item from the ranked
list above based on what Arun actually wants next (ask him if it's not obvious;
the AWS apply and the Phase 5 multi-tenancy build are the two biggest, and only one
of them, the AWS apply, has no design decisions left to make).
