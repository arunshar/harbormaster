# W4 operator plan for 2026-07-14

This is the chronological checklist for Arun's W4 AWS window on Tuesday, 2026-07-14 in `America/Los_Angeles`. The canonical command source remains `docs/runbooks/WAVE4_LIVE_WINDOWS.md`. Use this plan to control timing, identity, approvals, stop conditions, and evidence. Copy each `ARUN RUNS` block from the canonical runbook only when this checklist reaches that step.

## Outcome

W4 is complete only when all of the following are true:

1. KEDA scale from 0 to N and back to 0 is recorded with first successful signed inference timing.
2. Managed Flink backpressure is recorded from the bound Flink dashboard, with matching Kinesis and Flink lag evidence through drain.
3. The scheduled Phase 5 teardown guard deletes the EKS node group and cluster without a direct Lambda invocation.
4. Terraform state is reconciled only after AWS confirms those objects are absent.
5. All remaining transient W4 compute and network resources are removed, the route is back on ECS, the nightly teardown remains enabled and wet, and a final saved plan is clean. The new boundary version and ELB service-linked role intentionally persist.
6. The sanitized evidence handoff contains no binary plan, credentials, or presigned URL.

An unsuccessful measurement does not authorize a second unplanned load run. Record the failed criterion, continue directly to cleanup, and schedule a separate retry after inspecting the artifacts.

## Hard safety boundary

- Arun runs every AWS, Terraform, ECR, S3, and Kubernetes mutation.
- Codex may prepare code, commands, and read-only verification only.
- Never run `make destroy`.
- Never rerun `infra/aws/bootstrap.sh`.
- Keep the 75 USD hard budget and automatic spend-freeze action armed.
- Keep the nightly sweep enabled. It runs at 07:00 UTC, which is 00:00 PDT.
- Enter the MFA code only through the hidden prompt. Do not type it literally into a command or put it in a file, chat, or shell history. Do not persist AWS credentials or the Flink presigned dashboard URL.
- Use the administrator identity only through the IAM reconciliation in Sections 2 and 3. Use the assumed `harbormaster-platform` role for every command in Sections 4 through 12.
- Stop on an unexpected identity, budget state, plan action, guard value, resource replacement, authorization result, or cleanup result.

## Preparation snapshot from 2026-07-13

The local and read-only preparation run is preserved at:

```text
/Users/arunsharma/code/harbormaster-w4-prep-artifacts/20260713T091950Z
```

That run observed the following. Treat every AWS value as a snapshot that must be rechecked tomorrow.

- Repository commit tested: `e23ab19`.
- `make serve-install`: passed.
- `make serve-test`: 1,026 passed and 20 skipped.
- `make validate`: passed.
- `make flink-package`: passed.
- Flink ZIP SHA-256: `30d7024b4ebd6d907089ff56abe0437b9931a03b0c5e79ba4c5ca8ed0db383b3`.
- Required Flink ZIP members: all five present.
- Phase 5 renderer tests: 13 passed.
- Terraform format against the tracked CI view: passed.
- Checkov 3.3.6 against the tracked CI view: 0 new failures.
- TFLint 0.63.1 against the tracked CI view: passed.
- AWS account: `645322802947` under the `arun-admin` IAM user.
- Hard budget: 75 USD limit, 0 USD actual, 14.34 USD forecast.
- Automatic spend-freeze action: `STANDBY` for `harbormaster-platform`.
- Nightly schedule: enabled at `cron(0 7 * * ? *)` in UTC.
- Nightly target Lambda: `harbormaster-base-teardown`.
- Nightly Lambda: active but `DRY_RUN=true`.
- Permissions boundary: default version `v2`.
- EKS clusters: none.
- MSK clusters: none.
- SageMaker endpoints: none.
- Elastic Load Balancing service-linked role: absent.

Beyond the mandatory IAM reconciliation in Step 3, two additional snapshot-specific preconditions are expected to require human mutation before any EKS plan:

1. Create the Elastic Load Balancing service-linked role once.
2. Run the guard-only Stage 0 Terraform plan and apply to set the nightly teardown Lambda to `DRY_RUN=false`.

Do not assume either condition is unchanged tomorrow. Repeat the preflight.

## Recommended calendar block

Reserve 08:30 through 16:30 PDT. This leaves a large margin before the 00:00 PDT nightly sweep. The time bands are planning estimates, not pass criteria.

| Local time | Work | Maximum planned duration |
|---|---|---:|
| 08:30 | Local preparation and fresh artifact directory | 30 minutes |
| 09:00 | Admin read-only preflight and IAM reconciliation | 45 minutes |
| 09:45 | Mandatory guard-only Stage 0 | 30 minutes |
| 10:15 | EKS Stage 1 create and verification | 60 minutes |
| 11:15 | KEDA, image, and immutable manifest | 45 minutes |
| 12:00 | Managed Flink start and KEDA stabilization | 45 minutes |
| 12:45 | API retarget and bounded measurement | 45 minutes |
| 13:30 | ECS rollback, KEDA removal, and guard live-fire | 90 minutes |
| 15:00 | State reconciliation, final cleanup, and evidence handoff | 90 minutes |

Do not compress a plan review to meet the schedule. If EKS has not been created, it is safe to stop and reschedule. Once EKS or NAT exists, reserve enough time to finish cleanup in the same window.

## Terminal discipline

Use one primary terminal for the full window. A second terminal may show the optional read-only Kubernetes watch, but it must not issue mutations.

At the start of the primary shell:

```bash
set -euo pipefail
cd ~/code/harbormaster
```

Before every mutating command block:

1. Read the block and the stop condition below it.
2. Confirm the current caller with `aws sts get-caller-identity` when the identity could have changed or the session could have expired.
3. Confirm the plan file and summary labels match the current stage.
4. Review every create, update, replace, and delete action.
5. Apply only the exact saved binary plan whose SHA-256 matches its summary.
6. Run the stage's read-only verification before editing tfvars for the next stage.

If any command fails, preserve its output and stop that stage. Do not rerun an apply blindly. Determine whether Terraform completed, partially completed, or never started by reading state and AWS with read-only commands.

## Step 1: synchronize and prove the local build

Run Section 1 of the canonical runbook from a clean current `master`.

Required sequence:

1. `git status --short` must be empty.
2. `git pull --ff-only` must finish without a merge.
3. Record `git rev-parse HEAD` in the live artifact directory after it is created.
4. Run `make serve-install`.
5. Run `make serve-test`.
6. Run `make validate`.
7. Run `make flink-package`.
8. Verify the five required ZIP members exactly as listed in Section 1.
9. Record `shasum -a 256 dist/flink-app.zip`.

Create a fresh live artifact directory under the ignored `artifacts/w4/` path. Do not reuse the preparation directory or any previous W4 directory.

```bash
export STAMP=$(python3 -c 'from datetime import UTC, datetime; print(datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))')
export ARTIFACT_DIR="$PWD/artifacts/w4/$STAMP"
mkdir -p "$ARTIFACT_DIR"
git rev-parse HEAD | tee "$ARTIFACT_DIR/git-head.txt"
shasum -a 256 dist/flink-app.zip | tee "$ARTIFACT_DIR/flink-app.sha256"
printf '%s\n' "$ARTIFACT_DIR"
```

Checkpoint: the worktree is clean, the tests and Terraform validation pass, the ZIP is fresh, and `ARTIFACT_DIR` is printed and nonempty.

## Step 2: repeat the read-only AWS preflight as administrator

Run Section 2 exactly. The corrected runbook derives the Lambda function name from the schedule target ARN. It does not assume the schedule and Lambda have the same name.

Required verdicts:

- Caller account is exactly `645322802947`.
- Hard budget limit is 75 USD.
- Actual spend is below 75 USD.
- The automatic IAM spend-freeze action is `STANDBY`, targets `harbormaster-platform`, and names the exact spend-freeze policy.
- Nightly schedule is enabled at 07:00 UTC.
- Boundary default version is `v2` before reconciliation.
- `harbormaster-base-eks` is absent.
- No unexpected expensive MSK cluster or SageMaker endpoint is present.

Set `NIGHTLY_TEARDOWN_WET` only from the saved Lambda configuration. The 2026-07-13 snapshot was `false`, so expect Stage 0, but obey tomorrow's result.

The ELB service-linked-role lookup returned `NoSuchEntity` on 2026-07-13. If it is still absent, Arun runs the one create command in Section 2:

```bash
aws iam create-service-linked-role \
  --aws-service-name elasticloadbalancing.amazonaws.com
```

Immediately verify it with the read-only `aws iam get-role` command and save the result. If creation reports that the role already exists, verify the role, preserve the response, and do not retry.

Checkpoint: budget and guard evidence is saved, no W4 cluster exists, and the ELB service-linked role exists.

## Step 3: reconcile the boundary and platform role

Run Section 3 as administrator. This is not optional because W4 depends on the new effective-permission intersection.

Perform these substeps in order:

1. Inspect the committed boundary and platform policy statements locally.
2. Create one new boundary policy version and set it as default.
3. Save the returned version as `NEW_BOUNDARY_VERSION`.
4. Do not delete `v2`; it is the immediate rollback version.
5. Verify the budget-action role and its exact attach/detach policy scope.
6. Use the IAM simulator to prove the budget action can attach the spend freeze to `harbormaster-platform`.
7. Reconcile the existing platform role's inline IAM-management policy.
8. Update its maximum session duration to 28,800 seconds.
9. Run every positive and negative platform simulation in Section 3.

The expected simulation decisions are encoded in each helper invocation:

- bounded role management: `allowed`;
- pass role: `allowed`;
- EKS OIDC provider: `allowed`;
- instance profile: `allowed`;
- required service-linked role: `allowed`;
- platform self-mutation: `explicitDeny`;
- unrelated role creation: `implicitDeny`;
- boundary mutation: `explicitDeny`.

Stop if any result differs. Do not assume the platform role until all eight checks pass.

Assume `harbormaster-platform` with a direct MFA-backed administrator identity. Enter the MFA token through the hidden prompt. Verify the returned caller ARN starts with:

```text
arn:aws:sts::645322802947:assumed-role/harbormaster-platform/
```

Keep that shell for Sections 4 through 12. If it expires, first unset `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN`. Require the restored caller ARN to equal the direct administrator ARN saved during preflight. Then repeat the MFA assume-role block with a fresh token, export the new session values, and recheck the platform caller. Do not try to call STS through the expired exported session.

Checkpoint: all simulation artifacts pass and the active caller is the bounded platform role.

## Step 4: make the nightly teardown wet before planning EKS

If `NIGHTLY_TEARDOWN_WET=false`, run Stage 0 in Section 4. The 2026-07-13 snapshot makes this the expected path.

Edit only the four Stage 0 values in the gitignored tfvars:

```hcl
enable_phase1           = true
enable_nightly_teardown = true
teardown_dry_run        = false
enable_phase5           = false
```

Create `wave4-w4-nightly-guard.tfplan` through `scripts/plan_artifact.sh`. Before applying, require all of the following:

- plan SHA-256 equals the saved summary SHA-256;
- every changed address starts with `module.finops.`;
- no changed action contains `delete`;
- no Phase 5 address appears;
- no Phase 1 data store is deleted or replaced.

Arun then runs `make apply-plan PLAN="$PLAN_FILE"` and types `yes` only after that review.

Whether Stage 0 ran or was skipped, fetch the derived teardown Lambda again and require `DRY_RUN=false`. This assertion is mandatory. Stop before the EKS plan if it fails.

Checkpoint: the saved Lambda artifact proves the nightly guard is wet.

## Step 5: create the bounded EKS Stage 1 footprint

Set the complete Stage 1 tfvars block from Section 4. Important values:

- NAT enabled only for this window;
- Phase 5 enabled;
- Kubernetes provider access and KEDA still disabled;
- public EKS endpoint restricted to the operator's current `/32`;
- one desired node;
- Phase 5 guard wet with four-hour maximum age;
- ECS remains the active serving target.

Fetch the operator public IP immediately before the plan and insert exactly that `/32`. If the network changes later, stop and update it through a new reviewed plan rather than widening the CIDR.

Create the `wave4-w4-eks` saved plan. It may add EKS, one managed node group, NAT, the internal NLB, OIDC and bounded roles, and the Phase 5 guard. It may update the spend-freeze policy and nightly teardown coverage. It must not:

- delete or replace a Phase 1 data store;
- switch API Gateway away from ECS;
- create more than one worker;
- disable either teardown guard;
- open the EKS public endpoint beyond the single operator `/32`.

Apply the exact saved plan. Then run every read-only verification in Section
4. Require EKS 1.34, standard support, cluster `ACTIVE`, node group `ACTIVE`, desired size 1, schedule enabled, guard `DRY_RUN=false`, and maximum age 4.

Checkpoint: one healthy worker exists and both cost guards are armed.

## Step 6: enable Kubernetes access and install KEDA

Change only the two Stage 2 flags in Section 5. Generate and review the `wave4-w4-keda` saved plan, apply it, and update kubeconfig.

Verify:

- the single node is `Ready`;
- every KEDA pod is running;
- the `keda-operator` service account carries the Terraform-created IRSA annotation;
- operator logs contain no credential or CloudWatch authorization error.

Do not continue with an unhealthy operator. Preserve `kubectl describe` and pod logs in `ARTIFACT_DIR` before stopping.

Checkpoint: KEDA is healthy and authorized before any serving Deployment is applied.

## Step 7: build, push, resolve, and deploy one immutable image

Run Section 6. The image tag is a traceability label only. Kubernetes must use the repository plus resolved SHA-256 digest.

Required sequence:

1. Record the 12-character Git SHA.
2. Read the Terraform serving repository output.
3. Log Docker in to that exact ECR registry.
4. Build for `linux/amd64` and push the commit tag.
5. Resolve the pushed digest with `describe-images`.
6. Construct `IMAGE="$SERVING_REPO@$IMAGE_DIGEST"`.
7. Render the manifest through `make phase5-render-serving`.
8. Inspect the image, NodePort, and ScaledObject lines.
9. Apply that rendered artifact.

Before load, verify the deployed image equals `$IMAGE`, the NodePort is 30080, and both desired and available replicas are zero.

Checkpoint: one digest-pinned manifest is deployed at a zero-replica baseline.

## Step 8: upload and start Managed Flink

Run Section 7. Upload the already verified ZIP to a unique Git-SHA path. Put that exact key in tfvars and create the `wave4-w4-flink` saved plan.

Review and apply the plan, then start the application. Poll only the expected `READY`, `STARTING`, and `RUNNING` states. Exit on any other state. Save the application description and metric inventory.

Run the KEDA stabilization loop before retargeting API Gateway. It requires:

- at least 300 seconds since Flink became `RUNNING`;
- KEDA `Ready=True`;
- KEDA `Active=False`;
- desired replicas 0;
- available replicas 0;
- two consecutive valid samples.

The loop has a fixed upper bound. Stop if it does not produce two stable samples. Do not begin measurement from a nonzero Deployment.

Checkpoint: Flink is running and KEDA has returned to a proven zero baseline.

## Step 9: retarget only API Gateway

Change only `serving_target = "eks"`. Generate the `wave4-w4-retarget-eks` saved plan.

The plan must update the API Gateway route only. ECS remains live as the rollback backend. Reject the plan if it changes EKS, KEDA, Flink, a data store, networking, or ECS capacity.

Apply the exact plan. Do not use plain `curl` as a health check because the route requires SigV4.

Checkpoint: API Gateway targets EKS and ECS remains available for rollback.

## Step 10: execute one bounded measurement

Run the complete Section 9 block from the same shell. It creates one fresh UUID and binds all three tools to that run ID.

Start order is mandatory:

1. scale observer;
2. Flink dashboard capture;
3. Kinesis load generator after the observer writes its ready marker.

The declared load hypothesis is 5 rps steady state, a 400 rps burst from second 180 through second 195, and 600 seconds total. Do not modify those values during the run. The observer timeout is 1,800 seconds so it can record return to zero.

After completion, require:

- all three process exit statuses are saved;
- all three JSON artifacts report `status: completed`;
- all three use the same fresh run ID;
- scale events include `scale_requested`, `pod_ready`, `first_inference_success`, and `returned_to_zero`;
- the bound dashboard artifact reports all three backpressure conditions true;
- Kinesis and Flink lag artifacts cover the load start through return to zero and show later drain.

Kinesis lag alone does not prove Flink backpressure. If the dashboard criterion or any artifact fails, record the failure and continue immediately to rollback. Do not claim the criterion closed.

Checkpoint: evidence verdict is written, regardless of pass or fail.

## Step 11: restore ECS before removing any serving component

Set `serving_target = "ecs"` and generate the `wave4-w4-rollback-ecs` saved plan. It must be a route-only rollback. Apply it and run the signed inference command from Section 10. Require HTTP 200 with no error.

Only after that response:

1. delete the exact rendered Kubernetes manifest;
2. set `enable_phase5_keda = false`;
3. generate and apply `wave4-w4-uninstall-keda`;
4. verify no Helm release remains in state and no KEDA pod remains.

Checkpoint: user traffic is back on ECS and KEDA is absent.

## Step 12: prove the scheduled Phase 5 guard

Disable Terraform Kubernetes access, set the Phase 5 maximum age to zero, and set its schedule to every five minutes exactly as listed in Section 10. Generate and apply `wave4-w4-arm-live-fire`.

Do not invoke the Lambda directly. Start the read-only log tail and polling loop. Let Scheduler delete the node group and cluster. Confirmation requires `ResourceNotFoundException`, not an inferred timeout or empty local state.

The polling loop is bounded. If deletion is not confirmed, preserve logs and AWS descriptions. Do not remove cluster or node-group state. Leave the nightly teardown wet and stop for diagnosis.

Checkpoint: AWS confirms the cluster is absent and the guard logs are saved.

## Step 13: reconcile only confirmed missing state

List the two expected state addresses. Only after AWS confirms the cluster is not found, Arun runs the exact `terraform state rm` command in Section 11 for:

```text
module.eks_cluster[0].aws_eks_cluster.this
module.eks_node_group[0].aws_eks_node_group.this
```

Do not remove any other address. This is state reconciliation after an authorized external guard action, not a substitute for deleting a live resource.

Stop Managed Flink and poll until it is `READY`. Preserve the stopped application description.

Checkpoint: only the two confirmed-missing EKS objects were removed from state, and Flink is stopped.

## Step 14: apply the safe resting posture

Set the complete final tfvars block from Section 11. Key resting values are:

- NAT disabled;
- nightly teardown enabled and wet;
- Phase 5 disabled;
- Kubernetes access and KEDA disabled;
- public endpoint access disabled and CIDR list empty;
- desired nodes zero;
- ECS serving target restored;
- Flink code key empty.

Generate `wave4-w4-final-cleanup`. It may delete remaining Phase 5 resources and the Managed Flink application. It must not delete or replace Phase 1 state stores. Apply the exact reviewed plan.

Checkpoint: the final cleanup apply succeeds without touching Phase 1 data.

## Step 15: final verification and sanitized handoff

Run Section 12 in full. Required results:

- W4 EKS cluster absent;
- W4 NLB absent;
- Harbormaster NAT gateway absent;
- Harbormaster Elastic IP absent;
- Phase 5 guard schedule absent;
- Managed Flink application absent;
- nightly teardown schedule enabled;
- nightly teardown Lambda `DRY_RUN=false`;
- signed ECS inference returns HTTP 200;
- `wave4-w4-verified-clean` plan has zero add, change, and destroy actions.

Create the sanitized handoff from the explicit allowlist. Confirm it contains no `.tfplan`, credential, security token, signature, or presigned URL. Review every allowlisted file before sharing it.

Do not update `docs/drills/M3_backpressure_loadtest.md`, Phase 5 status, or war story P37 until the sanitized artifacts are available. Every reported number must be generated from those files.

## Artifact checklist

Before ending the window, confirm the live directory or sanitized handoff has the applicable files below:

- Git head and Flink ZIP SHA-256.
- Caller identity for administrator and platform-role phases.
- Budget, budget action, nightly schedule, and nightly Lambda preflight.
- Boundary before and after, budget-action policy, and IAM simulations.
- Every plan text, plan summary, and binary-plan SHA-256 comparison.
- EKS cluster, node group, guard schedule, and guard function descriptions.
- Kubernetes nodes, KEDA pods, IRSA service account, and serving inventory.
- Digest-pinned rendered serving manifest.
- Flink running description and metric inventory.
- KEDA stabilization JSONL.
- Load, scale timeline, Flink dashboard backpressure, process status, evidence verdict, and CloudWatch lag artifacts.
- ECS rollback inference result.
- Guard live-fire poll, follow log, final log, and deletion confirmation.
- Flink stopped description.
- Final EKS, NLB, NAT, Elastic IP, schedule, and Flink absence checks.
- Final nightly guard check, signed ECS inference, and zero-change plan.

## Work deliberately excluded from this window

Do not add any of the following tomorrow, even if W4 finishes early:

- Debezium AWS registration retry.
- P39 live key migration or derived-store rebuild.
- Boundary Part C Phase 1 least-privilege proof.
- Live RDS tenant-isolation drill.
- Live Bedrock prompt-leakage drill.
- CMK replacement window.
- SageMaker canary shift and rollback.
- Wave 5 load, soak, alarm, chaos, cost, or rollback-rehearsal work.

Each item needs its own scheduled human-run window, its own fresh artifacts, and the same budget and teardown controls.
