# Codex handoff (2026-07-12)

Read this file in full before touching anything. It supersedes
`sessions/CODEX_HANDOFF_2026-07-11.md` (that one predates the internal-completion
program: Waves 1-3, all of Phase 5, and the 2026-07-12 live AWS window). This is
the single, self-contained, current state of the Harbormaster repo, written so a
fresh Codex CLI session with no prior context can resume correctly.

## One-line status

Harbormaster (maritime AIS anomaly-detection platform: streaming + CDC + lakehouse
+ ML serving on AWS, training on MSI) is internally complete through Phase 5's
BUILD, pressure-tested, and now partially live-validated. `master` has Phases 0-5
merged. The Phase 5 phase gate is intentionally still OPEN pending three live legs
in a future AWS window (the "W4" window below). The most recent work (PR #6, the
W3 live window) applied the IAM boundary + apigw hardening + Phase 2 CDC live, found
and fixed six real infra bugs. The deferred Debezium connector-registration issue
is now fixed and verified on the local Debezium 2.7 / Connect 3.7 stack. The
corrected command has not been retried on AWS, so no new live-AWS claim is made.

## Repo facts

- Path: `~/code/harbormaster`. Remote: `https://github.com/arunshar/harbormaster.git`.
- Branch: `master`. Commit stack of note: Wave 1 merged (PR #3, `864562f`), Phase 5
  build merged (PR #4, `1ebd2e0`), Wave 3 pressure test merged (PR #5, `d38d8a5`),
  and the W3 live-window fixes merged as PR #6 (`86f3d63`). The current master also
  contains the local connector-registration fix described below. Check
  `git log --oneline -8` and `gh pr list` for the live state.
- Test command: `make serve-test` (`.venv/bin/python -m pytest -q`). There is NO
  `make test` target; do not invent one. cdc tests: `.venv/bin/python -m pytest cdc/tests -q`.
  Lint: `make serve-lint`. Terraform: `make validate` / `make plan` / `make apply`
  (against `infra/terraform/envs/base`; `terraform.tfvars` is gitignored).
- War stories: numbered P1-P40 in `PLATFORM_WAR_STORIES.md` on master; the six from
  the W3 window (below) are captured in the PR #6 commit message + the runbook but
  are NOT yet ported to `arunshar/debug-war-stories` (a follow-up).
- Live AWS: account 645322802947, us-east-1. After the W3 window, the stack is at
  **Phase 0/1-only standing** (serving on ECS Fargate + RDS + Kinesis + DynamoDB;
  no MSK, no CDC, no Redis; nothing billing beyond the small Phase 1 baseline). The
  `$75/mo` FinOps hard cap + nightly teardown Lambda are in force. **All AWS
  mutation is a human-run window, never unattended.**

## What is already applied live (do not re-derive)

- **IAM permissions boundary + API Gateway hardening** (the long-deferred item from
  the old handoff): APPLIED. `bootstrap.sh` created the boundary policy; the module
  roles carry `permissions_boundary`; the apigw route is `AWS_IAM` (SigV4) with
  throttling + access logging. The boundary policy is at **version v2** (added
  `kafka-cluster:*` and `ssmmessages:*` in the W3 window; see fix #4). Part C
  (switching the deploy identity to the boundary-gated `harbormaster-platform` role
  to prove least-privilege) is still NOT done and is the remaining honest gap on
  that row in `AB_MASTERCLASS_AUDIT.md` (keep it Partial until Part C).
- **DR-3 burn-rate CloudWatch alarms**: applied live in the W3 window.

## The six W3-window fixes (PR #6, all in `feat/wave4-w3-live-fixes`)

Each is a real bug that only a live run surfaced; five verified live, one is a note.

1. `modules/kda_flink`: KDA v2 rejects an empty-string property-map value; omit
   `quarantine_bucket` when empty via `merge()`.
2. `.dockerignore`: un-excluded `cdc` (broke `cdc/consumer/Dockerfile` COPY).
3. `modules/cdc_monitoring`: private-DNS Secrets-Manager/CloudWatch VPC endpoints'
   SG now allows in-VPC CIDR ingress (was scoped to only the slot-lag Lambda SG,
   silently timing out the Debezium container's GetSecretValue).
4. `harbormaster-permissions-boundary.json`: added `kafka-cluster:*` + `ssmmessages:*`;
   applied live as boundary policy v2.
5. `modules/ecs_connect` + `cdc/connector/config.py`: secret-to-file bridge
   (entrypoint wrapper writes the ECS-injected secret to `/dev/shm/secrets/password`,
   referenced via `DirectoryConfigProvider`). The later offline RCA proved that both
   providers were obscured by the runbook's shell transport, not broken in Connect.
6. Operational: re-fetch the RUNNING task ARN after every apply (rolling deploys run
   old+new tasks at once).

## Resolved after W3: Debezium connector registration

The W3 runbook embedded connector JSON in an unquoted remote heredoc. Bash expanded
both `${env:...}` and `${dir:...}` to empty before curl sent the request, so Kafka
Connect never saw either placeholder. Kafka 3.7 source confirms
`AbstractHerder.validateConnectorConfig` transforms before `Connector.validate()`;
the runtime uses the same transformer, and no `?force` validation bypass exists.

The fix base64-encodes the request payload, mirrors the DirectoryConfigProvider
bridge in kind, removes local literal-password bypasses, and waits for connector and
task state `RUNNING`. A fresh local Debezium 2.7 / Connect 3.7 run passed connector
registration and all five Phase 2 e2e criteria. Evidence:
`docs/drills/CDC_connector_registration_local_2026-07-12.md`. The corrected command
has not been retried on AWS. That optional live leg remains a future human-run window.

## Ranked open items (what to pick up)

### 1. The W4 live window (the Phase-5-gate-closing work; a human-run AWS window)

Three acceptance criteria have a live leg only a real cluster and clock can close;
the Phase 5 gate stays OPEN until they do. Runbook: `docs/runbooks/WAVE4_LIVE_WINDOWS.md`
(the "Window W4" section, step by step). Summary:
- (a) EKS + KEDA scale `0 -> N -> 0` on Kinesis/Kafka lag, with a **measured** (not
  estimated) cold-start latency.
- (b) A deliberate load spike triggers then resolves real Flink backpressure, with a
  documented postmortem (`docs/drills/M3_backpressure_loadtest.md`).
- (f) The EKS teardown-guard Lambda force-destroys the cluster on schedule at least
  once, demonstrated live. NOTE: the guard deletes AWS resources outside terraform,
  so the runbook includes a state-reconciliation step (`terraform state rm`) after.
Cost envelope: ~$0.20-3 in a bounded window (EKS control plane ~$0.10/hr flat),
inside the $75 cap, PROVIDED the teardown guard fires.

### 2. Multi-tenancy composite-key hardening (war story P39, from Wave 3)

Row-level security over single-column business keys is not isolation: a same-key
cross-tenant upsert 500s and can leak tenant-private annotations, and the CDC read
side is tenant-oblivious. The correct fix is composite `(tenant_id, key)` keys,
which ripples through the base DDL, the Debezium message-key mapper, and the registry
upserts. Documented as a known limitation, routed here on purpose (not a rushed
architecture change mid-window). See `docs/WAVE3_FINDINGS.md`.

### 3. Deferred robustness items (from Wave 3, `docs/WAVE3_FINDINGS.md`)

Pre-existing hardening work from the pressure test: flink `key_by` correctness,
an ingest `PutRecords` multi-round regression plus finding-ledger correction,
prism ellipse center, and the remaining test-strength mutants. The `PutRecords`
production mapping was later confirmed correct; finding 21 was a false positive.
None are live-cost items.

### 4. Structural / low-priority

CMK is authored behind `enable_cmk` (default false, never applied); a Phase 2 MSK
showcase and two-variant live SageMaker canary were set up but not fully exercised
(the canary actuator code is real and unit-tested); ECR `hm-pidpm-demo` cleanup; the
`~18 May 2027`-style FinOps discipline stands.

## Execution plan for the rest of the implementation (Codex)

This is the full remaining work, split by SAFETY. The split is the contract, not a
suggestion.

### A. Safe for Codex to do autonomously (no live AWS; all local + tested)

Do these in order; each is a normal PR to `master` with tests in the same change,
CI green before merge, one concern per PR.

Connector registration is complete locally, with its fix, regression tests, and
evidence artifact in the same change. Continue with:

1. **P39 multi-tenancy composite-key hardening** (open item #2). Composite
   `(tenant_id, key)` through the base DDL, the Debezium message-key mapper, and the
   registry upserts. RLS + cross-tenant tests against a local Postgres (the existing
   `make phase5-tenant-smoke` convention), never mocked.
2. **Robustness items** (open item #3): flink `key_by` correctness, ingest
   `PutRecords` multi-round test strength plus the finding-21 ledger correction,
   prism ellipse center, and remaining test-strength mutants. Finding 21's
   production mapping is already correct; its regression must fail the
   original-batch mutation. Each real code defect needs a test that fails before
   and passes after.
3. **War stories P41-P46** to `arunshar/debug-war-stories` (the six W3 fixes; content
   is in this file + the PR #6 commit + the runbook, so it is a copy-and-format job).

### B. Human-run live-AWS windows (Codex PREPARES and DRIVES WITH the human, never autonomous)

Codex may: write/adjust the terraform, generate the exact command sequences, do the
read-only verification calls, and reconcile state. Codex may NOT: run `terraform
apply`/`destroy`, `bootstrap.sh`, `aws ... modify/create/delete`, or any mutation on
its own. Every mutating command is pasted and run by the human in a scheduled window,
exactly as in the W1/W2/W3 precedent. Guardrails: `$75/mo` FinOps hard cap + nightly
teardown Lambda in force; always re-fetch the RUNNING task ARN after an apply; every
window ends back at Phase 0/1-only standing.

- **W4 window (closes the Phase 5 gate).** Full step-by-step in
  `docs/runbooks/WAVE4_LIVE_WINDOWS.md`, "Window W4": EKS + KEDA measured cold-start
  `0->N->0` (criterion a), Flink backpressure drill + `docs/drills/M3_backpressure_loadtest.md`
  postmortem (criterion b), and the live EKS teardown-guard force-destroy +
  `terraform state rm` reconcile (criterion f). Optional same-window: live RLS drill,
  a few live Bedrock calls. Grounds war story P37 (cold-start) either way.
- **W3-remainder (optional).** CMK apply + verify (RDS re-encryption forces a replace,
  so do it on a fresh Phase 1 window per the module doc) and the two-variant canary
  live weight-shift + forced revert (proves the DR-13 burn-rollback end to end).

### C. The production test plan (the Wave 5 core; human-run with Codex driving)

After W4, this is what makes Codex's handoff a real production sign-off, executed WITH
the human, same safety contract as B:

- **Cloud load test** replacing the M4-extrapolated `$/inference` with a measured
  number (closes the last "extrapolated, not measured" claim in `docs/HONESTY.md`).
- **Soak + alarm live-fire**: run the serving plane under sustained load, deliberately
  breach an SLO, and confirm the burn-rate composite alarm -> auto-rollback path fires.
- **Chaos drills** converting the remaining ANTICIPATED war stories to grounded where
  feasible (P1 hot shard, P3 snapshot lock, P4 async burst drop, P5 cold-read throttle,
  P6 small-file explosion, P8 provider drift) with runbook pointers + verification bars.
- **Boundary Part C** least-privilege proof: switch the deploy identity to the
  boundary-gated `harbormaster-platform` role and re-run a Phase 1 plan/apply to prove
  it can create the bounded roles but cannot escalate. Only then does the IAM row in
  `AB_MASTERCLASS_AUDIT.md` move off Partial.
- **Cost audit + rollback rehearsal**, each with a runbook pointer and a pass bar.

Deliverable: update `docs/HONESTY.md` and the audit doc to their final measured states,
and close the Phase 5 gate in `docs/phases/PHASE_5.md` with the real numbers.

## Guardrails to carry forward

- No unattended AWS mutation, ever; windows are human-run and scheduled.
- Honest science: no live-behavior claims from unapplied infra; authored-not-applied
  caps at Partial in `AB_MASTERCLASS_AUDIT.md`; every reported number comes from a
  run you executed.
- New logic ships with tests in the same change; 90% line+branch on new/changed
  modules; repo floor `fail_under=80`.
- Commits authored the human, no AI co-author trailer, no em dashes.
- ADR 0001/0003/0004 boundaries stand (event-time windowing is a deliberate deferral,
  not a gap). FDE artifacts stay SIMULATED-labeled per `docs/HONESTY.md`.

## Suggested first move

Read `git log --oneline -8`, `gh pr list`, and `docs/runbooks/WAVE4_LIVE_WINDOWS.md`.
If the goal is to close the Phase 5 gate, schedule the W4 human-run window. For safe
autonomous work, start P39 composite-key hardening as its own tested PR. Do not retry
the optional connector command on AWS except in a scheduled human-run window.
