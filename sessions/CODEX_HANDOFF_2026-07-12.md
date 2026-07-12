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
and fixed six real infra bugs, and left exactly one thing deferred to free offline
debugging: Debezium connector registration.

## Repo facts

- Path: `~/code/harbormaster`. Remote: `https://github.com/arunshar/harbormaster.git`.
- Branch: `master`. Commit stack of note: Wave 1 merged (PR #3, `864562f`), Phase 5
  build merged (PR #4, `1ebd2e0`), Wave 3 pressure test merged (PR #5, `d38d8a5`),
  and the W3 live-window fixes on PR #6 (`feat/wave4-w3-live-fixes`, head `8ec04bf`).
  Check `git log --oneline -8` and `gh pr list` for the live state; PR #6 may be
  merged by the time you read this.
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
   referenced via `DirectoryConfigProvider`), replacing the non-working `${env:...}`.
6. Operational: re-fetch the RUNNING task ARN after every apply (rolling deploys run
   old+new tasks at once).

## Ranked open items (what to pick up)

### 1. Debezium connector registration (the deferred W3 item; free to debug on local kind)

**Status:** blocked at connector-config *validate* time, diagnosed but unfixed.
Everything else in the Phase 2 CDC pipeline is proven live (MSK cluster up; the
Connect worker authenticating to MSK via IAM and joining group `hm-connect` gen 1;
the consumer running; RDS logical replication enabled). The one failing step is the
Debezium PUT `/connectors/harbormaster-postgres/config`, which returns
`"the password is an empty string"`.

**What was ruled out (do not re-do):** it is NOT the stale-task ARN (verified
against the confirmed-new task-def revision), NOT a secret-injection problem (the
`/dev/shm/secrets/password` file was verified present, 28 bytes, `kafka:kafka 0600`),
and NOT provider-specific: BOTH `${env:HM_PG_PASSWORD}` (against a present env var)
AND `${dir:/dev/shm/secrets:password}` (against a present file) resolve to EMPTY.
So Kafka Connect's `ConfigTransformer` is not resolving ANY `${provider:...}`
reference during connector-config VALIDATION in this Debezium 2.7 / Connect 3.7
image; the runtime path may differ from the validate path. An 11-agent RCA
(archived; the winning fix was the dir-provider bridge, which is correct for the
secret-delivery half but did not resolve the validate-time behavior).

**How to debug (free, fast):** reproduce on the local kind CDC stack (`make cdc-up`,
then the cdc smoke/e2e targets) where iteration costs nothing. Hypotheses to test
there: (a) whether the worker actually loaded `config.providers=dir` (check the
worker startup log for the provider registration line); (b) whether Connect 3.7's
`AbstractHerder.validateConnectorConfig` applies the transformer before
`Connector.validate()` for this connector (a known area of version-specific
behavior); (c) whether posting the connector and letting it reach RUNNING (where the
transformer definitely runs) works even though validate reports empty; (d) as a last
resort, a `PUT` with `?force` semantics or the `/connector-plugins/.../config/validate`
endpoint to see the transformed values echoed. The infra fix (dir-provider + wrapper)
is already correct and merged; only the Connect-version resolution behavior remains.
This leg is OPTIONAL (not a Phase 5 gate criterion).

### 2. The W4 live window (the Phase-5-gate-closing work; a human-run AWS window)

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

### 3. Multi-tenancy composite-key hardening (war story P39, from Wave 3)

Row-level security over single-column business keys is not isolation: a same-key
cross-tenant upsert 500s and can leak tenant-private annotations, and the CDC read
side is tenant-oblivious. The correct fix is composite `(tenant_id, key)` keys,
which ripples through the base DDL, the Debezium message-key mapper, and the registry
upserts. Documented as a known limitation, routed here on purpose (not a rushed
architecture change mid-window). See `docs/WAVE3_FINDINGS.md`.

### 4. Deferred robustness items (from Wave 3, `docs/WAVE3_FINDINGS.md`)

Pre-existing bugs found by the pressure test and left for a hardening pass: flink
`key_by` correctness, ingest `PutRecords` partial-failure retry, prism ellipse
center, and the remaining test-strength mutants. None are live-cost items.

### 5. Structural / low-priority

CMK is authored behind `enable_cmk` (default false, never applied); a Phase 2 MSK
showcase and two-variant live SageMaker canary were set up but not fully exercised
(the canary actuator code is real and unit-tested); ECR `hm-pidpm-demo` cleanup; the
`~18 May 2027`-style FinOps discipline stands.

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
If the goal is to close the Phase 5 gate, schedule the W4 human-run window. If the
goal is to finish the optional CDC leg, reproduce the connector-registration issue on
the local kind stack first (free) and confirm a fix there before any paid live retry.
Everything unit-testable is green on master; the only open work is live windows and
the offline connector debug.
