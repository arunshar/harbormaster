# W4 Stage 1 partial apply, 2026-08-04

## Scope and verdict

This record covers the human-run W4 Stage 1 Terraform attempt and the later
read-only reconciliation. It is an evidence record, not an executable recovery
runbook. Every live value below is a time-specific observation from before the
07:00 UTC nightly sweep.

VERDICT: PARTIAL APPLY, RECOVERY DEFERRED.

No Phase 5 gate criterion closed. No EKS cluster was created, no KEDA or Flink
measurement ran, and the Phase 5 guard schedule did not fire. Criteria (a),
(b), and (f) remain open.

## Timeline

1. The first Stage 1 plan failed before deployment because two API Gateway
   resource counts depended on apply-time NLB values. No apply command ran from
   that plan. PR #37 made both decisions plan-time known.
2. A replacement saved plan was generated from merge commit `a1b60fa`. Its
   audited shape was 50 creates, 0 updates, and 0 deletes. The API route remained
   on ECS, KEDA remained disabled, both teardown guards were wet, and the worker
   shape remained one Spot node.
3. Arun approved and ran the exact checksum-bound plan. Terraform created part
   of the footprint, then exited nonzero while setting reserved concurrency on
   the newly created guard Lambda.
4. Read-only reconciliation proved that Terraform retained ownership of the
   partial objects. The Lambda was not orphaned; it was the sole tainted state
   instance and its live configuration matched the reviewed plan except that no
   reserved concurrency had been accepted.
5. PR #38 removed the unsupported reserved-concurrency setting, documented the
   account-quota rationale, and added regression coverage. It merged as
   `76c4522` after all 10 CI checks passed.
6. A separately reviewed state-only recovery helper passed its read-only mode.
   Arun started the helper and entered TOTP, but its 13:20 PDT cutoff arrived
   while it was waiting for the exact approval phrase. Arun interrupted it.
   Post-abort read-only checks proved that no untaint command ran.

## Primary local evidence

The live artifact root is local, ignored, and mode 700:

```text
artifacts/w4/20260804T190530Z
```

Key files and immutable hashes:

```text
wave4-w4-eks.tfplan
sha256=18f617d5197d28eb0c3f08f43e9d7b58ff015f4794913927a48c4431c8e0f4c2

wave4-w4-eks.plan.json
sha256=2dbb4a6036770a3790834a4e520d2ee3b840b03a7616f687ca37938dda77857b

wave4-w4-eks.apply.log
sha256=330361d3c691443259e455c0fc97cb5990f00d9294b7bbd9bd067f494161a77a
```

The final pre-approval reconciliation artifacts are under:

```text
artifacts/w4/20260804T190530Z/stage1-untaint-20260804T201513Z
```

That directory contains 70 mode-600 files, including the state snapshot,
address-set comparison, S3 state metadata, caller identities, budget and guard
checks, live Lambda projection, resource inventory, and absence checks. The raw
state snapshot can contain sensitive values and must remain local and mode 600.

The separate strict post-abort read-only checkpoint is under:

```text
artifacts/w4/20260804T204056Z-post-abort-readonly
```

Its durable local fingerprints are:

```text
checkpoint.json
sha256=ef22a26c87c34788dfab7471b51c3a59a485b71303f09a3d0c841d76c448779f

terraform.tfstate
sha256=8d86b56221ef8447d3429845fe4f80daec77dc620143e5f5110b1e4330f9049b

evidence-files.sha256
sha256=152a9600315f97e2d8467f1652f323e11d3c4d0bc9523ec9f1a12f891ed21a25
```

That checkpoint was generated at `2026-08-04T20:45:57Z` and records its audit
mode as `strictly_read_only`. The directory is mode 700 and all evidence files
are mode 600. The raw state and AWS responses remain ignored, local-only
evidence.

## Failure and root cause

Terraform created the guard Lambda, assigned its state ID, and then called
`PutFunctionConcurrency`. AWS rejected reserved concurrency `1` because the
account had a regional concurrency quota of 10 and requires at least 10
executions to remain unreserved. The observed apply error was:

```text
InvalidParameterValueException: Specified ReservedConcurrentExecutions for
function decreases account's UnreservedConcurrentExecution below its minimum
value of [10].
```

This was a quota-floor incompatibility in the authored Lambda resource, not a
missing Lambda, secret-delivery failure, or untracked orphan. PR #38 removed
`reserved_concurrent_executions = 1`. The recurring schedule is 30 minutes,
the handler timeout is 120 seconds, and the handler converges on retries. The
focused regression run passed 39 tests; the full local suite passed 1,113 tests
with 20 skipped. Ruff and Terraform validation passed, then all 10 GitHub CI
checks passed before merge.

## Last verified pre-sweep Terraform checkpoint

The last read-only checkpoint before the nightly sweep reported:

```text
state format version=4
serial=68
lineage=419a8985-87a0-4470-0b20-25f2ef23f7d4
S3 VersionId=d4Peikpxyi7mLw5NvB4fcVXdJVRXGOXL
S3 ETag="996c4f487d5d42790527afd72b2752ed"
tracked planned creates=28
remaining planned creates=22
tainted instances=1
backend lock=absent
```

The sole tainted address was:

```text
module.eks_teardown_guard[0].aws_lambda_function.guard
```

The live Lambda was `Active`, its last update was successful, `DRY_RUN=false`,
`MAX_AGE_HOURS=4`, and reserved concurrency was unset. Its code SHA, role, KMS
key, handler, runtime, timeout, tracing mode, dead-letter target, environment,
and tags matched the state projection. Repeated `terraform state pull` calls
can reorder `check_results`, so the recovery helper compared a deterministic
sorted fingerprint instead of treating raw JSON byte order as semantic drift.

The 22-create remainder is evidence about that exact pre-sweep state only. It
must not become an expected-count assertion for the next plan.

## Last verified pre-sweep live footprint

Tracked and live:

- NAT gateway `nat-0c654c7de61dcba9d`, state `available`.
- Elastic IP allocation `eipalloc-0d74779eda359d843`, public address
  `100.55.209.40`.
- Internal NLB ARN ending in `/942337b4be699b09`, state `active`.
- Target group ARN ending in `/bae9617d249cf658`, TCP port 30080.
- Guard Lambda `harbormaster-base-eks-teardown-guard`, active and wet.
- Supporting NLB and node security groups, launch template, guard IAM roles and
  policy, KMS key and alias, log group, NLB listener, private NAT routes, and a
  dormant API Gateway EKS integration.

Verified absent:

- EKS cluster `harbormaster-base-eks`.
- EKS managed node group, cluster roles, OIDC provider, cluster KMS alias, and
  control-plane resources.
- Phase 5 guard schedule, scheduler invoke policy, and Lambda scheduler
  permission.

The active API Gateway route still targeted ECS integration `86jwgmh`. The
dormant EKS integration was `ezhhz4c`; its existence was not live serving
evidence.

## Cost guards at the checkpoint

The saved read-only artifacts reported:

```text
hard budget limit=75 USD
actual spend=0 USD
forecast spend=32.823 USD
budget action=AUTOMATIC, STANDBY
nightly schedule=ENABLED, cron(0 7 * * ? *)
nightly Lambda=Active, LastUpdateStatus=Successful, DRY_RUN=false
```

The NAT gateway, Elastic IP, and NLB were billable partial resources. The wet
nightly Lambda is designed to request deletion of project-tagged W4 NLB and NAT
resources at 07:00 UTC and release a project-tagged Elastic IP only after it is
unattached. Those asynchronous actions can change live AWS without updating
Terraform state.

## Clean cutoff abort

The untaint helper reached its approval prompt with state serial `68`, the
pinned S3 VersionId, the exact Lambda revision, all cost guards passing, no
writer, and no backend lock. The 13:20 PDT cutoff then passed. Arun pressed
Ctrl+C. The terminal printed `Received INT.` and returned to the shell prompt.

Post-abort read-only verification found no helper or Terraform process, no
backend lock, serial `68`, one tainted Lambda, and the same S3 VersionId and
ETag. No state or AWS mutation occurred during the recovery attempt.

## Next-window boundary

The old binary plan, plan summary, label, checksum, and apply helper are
permanently consumed. They are retained only as evidence and must never be
reused.

Before any next mutation, all live values above must be rechecked after the
07:00 UTC sweep in a fresh artifact directory. If state and live AWS still prove
the exact guarded conditions, Arun may run a newly generated, separately
reviewed state-only reconciliation helper. Otherwise recovery requires a new
reviewed path. In every case, the next Terraform plan must have a new recovery
label and path, and its actual create, update, replace, and delete actions must
be audited without assuming the prior 22-create remainder.
