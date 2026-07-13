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
P39 composite-key hardening is also implemented and verified locally against
PostgreSQL 16, two local production-image containers, and a fresh kind CDC stack.
Its live Postgres migration and tenant-qualified DynamoDB/Redis rebuild have not run.
The Flink malformed-key defect and the `PutRecords` finding-21 test-strength gap
are also fixed and verified locally. The final near-pole prism projection debt is
fixed and locally regression-tested as well. None establishes new live AWS behavior.

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
- War stories: numbered P1-P46 in `PLATFORM_WAR_STORIES.md` on master. P41-P46
  preserve the six W3 findings below with their live-versus-local evidence boundaries.
  All 46 platform stories have been ported to `arunshar/debug-war-stories`.
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

## Ranked work items and current status

### 1. The W4 live window (the Phase-5-gate-closing work; a human-run AWS window)

Three acceptance criteria have a live leg only a real cluster and clock can close;
the Phase 5 gate stays OPEN until they do. Runbook: `docs/runbooks/WAVE4_LIVE_WINDOWS.md`
(the full W4 runbook, canonical Sections 1-12). Summary:
- (a) EKS + KEDA scale `0 -> N -> 0` on Kinesis/Kafka lag, with a **measured** (not
  estimated) cold-start latency.
- (b) A deliberate load spike triggers then resolves real Flink backpressure, with a
  documented postmortem (`docs/drills/M3_backpressure_loadtest.md`).
- (f) The EKS teardown-guard Lambda force-destroys the cluster on schedule at least
  once, demonstrated live. NOTE: the guard deletes AWS resources outside terraform,
  so the runbook includes a state-reconciliation step (`terraform state rm`) after.
Cost envelope: ~$0.20-3 in a bounded window (EKS control plane ~$0.10/hr flat),
inside the $75 cap, PROVIDED the teardown guard fires.

### 2. Multi-tenancy composite-key hardening (war story P39, locally complete)

Row-level security over single-column business keys is not isolation: a same-key
cross-tenant upsert 500s and can leak tenant-private annotations, and the CDC read
side was tenant-oblivious. The hardening now uses composite `(tenant_id, key)` keys
through the base DDL and registry/HITL conflict targets, explicit sentinel backfill,
tenant-qualified Debezium envelopes, DynamoDB partitions, Redis keys, and
`WatchlistLookup`. The explicit migration and runtime schema bootstraps share an
advisory lock; schema and RLS errors fail fast instead of silently falling back to
memory.

Local evidence on 2026-07-13: 10 PostgreSQL integration tests passed; the tenant
smoke passed against a throwaway non-superuser PostgreSQL 16 owner; two local
production-image containers, each with two Uvicorn workers, preserved same-MMSI
isolation; a fresh kind CDC smoke passed in 4.28 seconds; all five Phase 2 e2e
criteria passed in 36.41 seconds. See `docs/drills/P39_test_suite.md`,
`docs/drills/P39_local_cdc_smoke.md`, and
`docs/runbooks/P39_COMPOSITE_KEY_MIGRATION.md`.

This closes the safe-autonomous code item only. No live AWS database was migrated,
and no live DynamoDB or Redis state was rebuilt. That cutover remains human-run if
the live co-tenant deployment is scheduled.

### 3. Robustness closure (from Wave 3, `docs/WAVE3_FINDINGS.md`)

The Flink `key_by` defect from finding 4 and the `PutRecords` test-strength
correction from finding 21 are locally complete. Records rejected by the Flink
JSON and MMSI parser now use sentinel key `-1` and return through `_quarantine`
before keyed-state access.
The focused source test run passed 93 tests at 99.64% line and branch coverage,
and isolated checks passed against the packaged Flink ZIP. No Managed Flink job
was run. The sentinel removes the pre-quarantine exception but can still become
a hot key group during sustained malformed traffic. The prism ellipse-center
and antimeridian defects are locally complete. Wrapped longitude math follows
the shortest path, seam-crossing output is a normalized MultiPolygon, Boolean
geometry preserves GeoJSON ring winding, and DRM compares component bounds.
The near-pole kernel now uses a spherical azimuthal-equidistant projection
centered on the active foci's spherical midpoint, with wrapped haversine focus
distance and a numerically stable inverse. North and south non-containing
footprints pass at latitudes 89.9999 and 89.99999; a requested ellipse or MOBR
that contains or touches either pole raises a deterministic domain error, as do
antipodal or numerically singular foci. Adaptive sampling keeps supported
rotated footprints valid, conservative MOBR polygonization preserves the
downstream bounds contract, and corner-only mapping retains infeasible
zero-axis prisms. The focused geometry consumer run passed 75 tests at 90.85%
combined line and branch coverage. The full local gate passed with 1,094 tests
at 83.86% total coverage, and the serving Docker smoke returned HTTP 200 for
health and a near-pole score request. This is local evidence, not a
deployed-service claim. Bedrock
forbidden-vocabulary and inclusive-score boundaries are pinned, as are
disagreement usable-window and q95 boundaries. Tenant-drift ordering is pinned
under reverse insertion, and four hand-computed PPO cases pin the clipped
surrogate across both advantage signs and both clip sides. The ordered
robustness queue is complete. See
`docs/drills/FLINK_MMSI_KEY_LOCAL_2026-07-13.md` and
`docs/drills/ANTIMERIDIAN_PRISM_LOCAL_2026-07-13.md`, and
`docs/drills/NEAR_POLE_PRISM_LOCAL_2026-07-13.md`.

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

Connector registration is complete locally, including the bounded retry for the
post-PUT status-visibility race, with regression tests and fresh kind evidence.
P39 composite-key hardening is also complete locally, with real PostgreSQL,
production-image, and fresh kind CDC evidence. Its live migration and derived-store
rebuild remain outside the autonomous boundary.

All ranked Section A work is complete. The final port found that the target mirror
stopped at P28, so P29-P46 were merged as `arunshar/debug-war-stories` PR #1 on
2026-07-13. P29-P40 came from canonical master after Harbormaster PR #22 corrected
P31's source-path provenance. P41-P46 came from Arun-authored archival commit
`e2f0f62`, which Harbormaster PR #27 made canonical and remotely reachable before
this provenance correction. The mirror contains 106 journal stories plus 46
platform stories, 152 source entries. Canonical-to-mirror text synchronization and
editorial curation are maintained as separate archive changes; neither is a Phase 5
implementation gate or evidence for this provenance correction.

### B. Human-run live-AWS windows (Codex PREPARES and DRIVES WITH the human, never autonomous)

Codex may: write/adjust the terraform, generate the exact command sequences, do the
read-only verification calls, and reconcile state. Codex may NOT: run `terraform
apply`/`destroy`, `bootstrap.sh`, `aws ... modify/create/delete`, or any mutation on
its own. Every mutating command is pasted and run by the human in a scheduled window,
exactly as in the W1/W2/W3 precedent. Guardrails: `$75/mo` FinOps hard cap + nightly
teardown Lambda in force; always re-fetch the RUNNING task ARN after an apply; every
window ends back at Phase 0/1-only standing.

- **W4 window (closes the Phase 5 gate).** Full step-by-step in
  `docs/runbooks/WAVE4_LIVE_WINDOWS.md`, canonical Sections 1-12: EKS + KEDA measured cold-start
  `0->N->0` (criterion a), Flink backpressure drill + `docs/drills/M3_backpressure_loadtest.md`
  postmortem (criterion b), and the live EKS teardown-guard force-destroy +
  `terraform state rm` reconcile (criterion f). The measurement grounds the observed
  cold-start behavior either way; P37 becomes a grounded SLO-breach story only if the
  measured value crosses the documented tier threshold.
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

Deliverable: complete the post-gate production sign-off by updating
`docs/HONESTY.md` and the audit doc to their final measured states with the real
numbers. A successful W4 already closes the Phase 5 gate; Wave 5 does not reopen
or re-close it.

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
autonomous work, Section A is complete. Do not retry the optional connector command
or run the P39 cutover on AWS except in a scheduled human-run window.
