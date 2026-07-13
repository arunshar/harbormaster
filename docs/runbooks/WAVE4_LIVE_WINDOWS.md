# Runbook: Wave 4 live validation windows (W3 + W4)

Arun-run, two dedicated AWS windows. This is the last work before the Phase 5
gate can close and Wave 5 (Codex production handoff) can start. Account
645322802947, region us-east-1. `terraform apply`/`destroy` and any AWS
mutation are commands you run yourself; Claude drives the surrounding plan,
file edits, and verification reads.

## W3 live-run outcome (2026-07-12)

W3 ran live and did its job: it caught six authored-but-never-live-tested bugs,
each fixed in the same session (see the `feat/wave4-w3-live-fixes` commit).
Applied and verified live: Wave 0 IAM boundary (Part A + B) and apigw hardening,
the burn-rate alarms, and the full Phase 2 CDC infra (MSK Serverless, Debezium
connect/consumer on Fargate, Redis, slot-lag monitor). Proven end to end up to
connector registration: the MSK cluster, the Connect worker authenticating to
MSK via IAM and joining its group, the consumer running, RDS logical replication
enabled. The six fixes:

1. `modules/kda_flink`: KDA v2 rejects an empty-string `quarantine_bucket`
   property-map value; the key is now omitted when empty via `merge()`.
2. `.dockerignore`: un-excluded `cdc` (broke `cdc/consumer/Dockerfile`'s COPY).
3. `modules/cdc_monitoring`: the private-DNS Secrets-Manager/CloudWatch VPC
   endpoints' SG now allows in-VPC (CIDR) ingress, not just the slot-lag
   Lambda's SG (was silently timing out the Debezium container's GetSecretValue).
4. `harbormaster-permissions-boundary.json`: added `kafka-cluster:*` (MSK IAM
   SASL auth) and `ssmmessages:*` (ECS Exec); applied live as policy version v2.
5. `modules/ecs_connect` + `cdc/connector/config.py`: secret-to-file bridge
   (entrypoint wrapper writes the ECS-injected secret to `/dev/shm/secrets/password`,
   referenced via `DirectoryConfigProvider`). The later offline RCA showed that
   the runbook transport, not the provider, erased the placeholder.
6. Operational: always re-fetch the RUNNING task ARN after an apply (ECS runs
   old+new tasks during a rolling deploy).

RESOLVED OFFLINE 2026-07-12: connector registration was blocked by the ECS
Exec request transport, not by Kafka Connect. The runbook used an unquoted
remote heredoc, so Bash expanded both `${dir:...}` and `${env:...}` to empty
before curl sent the JSON. Kafka Connect 3.7 transforms provider references
before connector validation, and there is no validate/runtime bypass. The
registration helper now base64-encodes the JSON, the local kind deployment
mirrors the DirectoryConfigProvider bridge, and a fresh local Debezium 2.7 /
Connect 3.7 run reached connector `RUNNING` and task `RUNNING`; all five Phase 2
e2e checks also passed. Evidence: `docs/drills/CDC_connector_registration_local_2026-07-12.md`.
The corrected command has not been retried on AWS, so no live-AWS completion is
claimed. Phase 2 was torn down at W3 window end to stop MSK billing. The MSK/CDC
leg remains OPTIONAL (not a Phase 5 gate criterion); the gate-closing legs are
all in the W4 window below.

## Read this first: current live state (checked 2026-07-12)

- **Phase 1 is already live and has been since 2026-07-04.** RDS
  `harbormaster-base-pg` (available), Kinesis `harbormaster-base-ais-raw`
  (active), ECS service `harbormaster-base-serving`, DynamoDB
  `harbormaster-base-feast-online` all exist right now. `enable_phase1 = true`
  in your committed tfvars. This is a real 8-day-old standing cost (small:
  db.t4g.micro + one Fargate task + Kinesis + DynamoDB), not new spend Wave 4
  introduces.
- **`teardown_dry_run = true` in your tfvars.** The nightly teardown Lambda
  has been logging what it would tear down, not actually doing it, this whole
  time. Worth a deliberate decision, not an oversight left running: either
  flip it to `false` now (recommended, closes the exact gap Phase 2's MSK
  $18/day risk exists because of) or consciously keep it in dry-run and rely
  on manual teardown discipline through Wave 4.
- **The IAM permissions boundary is NOT applied yet** (confirmed live:
  `aws iam get-policy` for `harbormaster-permissions-boundary` returns
  `NoSuchEntity`). This is your own separate Wave 0 item
  (`IAM_BOUNDARY_APPLY.md`), authored, never applied. It is not a Phase 5
  dependency, but Part A of it is free, standing, and takes five minutes;
  folding it into the start of W3 (before anything billable spins up) is the
  cheap, sensible sequencing, not a requirement.
- **No EKS cluster, no MSK cluster, no SageMaker endpoint exist right now.**
  Phase 5's cluster, Phase 2's MSK, and Phase 3's endpoint are all
  authored-not-applied, exactly as documented.
- **ECR `hm-pidpm-demo` is already gone.** It does not appear in
  `aws ecr describe-repositories` today, so the "delete it" item on the old
  W3 checklist is already satisfied, nothing to do.
- **Current CMK alias `alias/harbormaster-*` does not exist.** `enable_cmk`
  is authored, unapplied, as documented.

## What actually closes the Phase 5 gate vs. what's a bonus demo

`docs/phases/PHASE_5.md`'s acceptance criteria (c), (d), (e), (g) are already
satisfied structurally (local Postgres RLS test, Bedrock prompt-leakage test,
PPO fixture test, import-graph pin) and proven in `tests/e2e/test_phase5.py`.
Only three criteria have a live leg that only a real cluster and a real clock
can close, and those three are what W4 must produce:

- **(a)** measured (not estimated) KEDA cold-start, 0 -> N -> 0
- **(b)** a real Flink-backpressure episode with a documented postmortem
- **(f)** the EKS teardown-guard Lambda actually force-destroying the cluster,
  demonstrated live

Everything else in this runbook (CMK apply, canary live shift, live Bedrock
calls, a live RLS drill against the real RDS instance) is real, valuable
showcase work the master plan named, but it is not gating. Treat (a)/(b)/(f)
as the must-do; treat the rest as do-if-time-permits in the same windows.

---

## Window W3: MSK showcase + CMK + canary live shift + plan artifacts

Budget: MSK Serverless ~$0.75/cluster-hour (~$18/day if forgotten, so this
window has a hard start/stop discipline). CMK ~$1/month standing once
enabled. A 2–3 hour window with a forced teardown at the end: a few dollars
total.

### W3.0 Optional: fold in Wave 0 Part A (IAM boundary hardening, free, first)

```
cd ~/code/harbormaster
aws sts get-caller-identity   # confirm arn:...:user/arun-admin
bash infra/aws/bootstrap.sh --dry-run
bash infra/aws/bootstrap.sh
aws iam get-role-policy --role-name harbormaster-platform \
  --policy-name harbormaster-iam-management \
  --query 'PolicyDocument.Statement[?Effect==`Allow`]'
aws iam get-policy --policy-arn arn:aws:iam::645322802947:policy/harbormaster-permissions-boundary
```
No Allow statement should grant a write `iam:*` on `Resource "*"`; the
boundary policy should now exist. This is free and standing; do it once and
never again. (Part B of that runbook, the module-role boundaries + apigw
hardening, is optional here too since Phase 1 is already applied without
it; folding it in means one more `make plan`/`make apply` cycle against the
already-live Phase 1 stack. Your call whether to do it this window or a
separate one.)

### W3.1 Baseline plan artifact (before anything else changes)

```
scripts/plan_artifact.sh wave4-w3-baseline
```
Expect `0 to add, 0 to change, 0 to destroy` against your current
`enable_phase1=true` committed tfvars (nothing else flipped yet). If it is
not zero, stop and reconcile the drift before proceeding.

### W3.2 Phase 2 MSK showcase (full detail: `PHASE_2_AWS_SHOWCASE.md`)

Condensed sequence, exact commands already in that runbook:

```
make cdc-lambda-package
```
In `terraform.tfvars`: `enable_phase2 = true` (leave `cdc_connect_image` /
`cdc_consumer_image` empty).
```
scripts/plan_artifact.sh wave4-w3-phase2-infra
make apply    # type yes
```
Build + push both images (M-series Mac: `--platform linux/amd64` or the
tasks die on exec format), then set `cdc_connect_image` /
`cdc_consumer_image` to the pushed URIs and:
```
scripts/plan_artifact.sh wave4-w3-phase2-services
make apply
aws ecs wait services-stable --region us-east-1 \
  --cluster harbormaster-base-cluster \
  --services harbormaster-base-cdc-connect harbormaster-base-cdc-consumer
```
Register the connector (in-VPC via ECS exec, section 5 of that runbook),
then run the five acceptance checks (section 6): flag-to-scored latency,
replay-no-duplicates hash check, Debezium-restart-loses-nothing, delete
removes from watchlist, slot-lag alarm fires on a stalled consumer. Each
has the exact `aws` command in that file; nothing to adapt.

### W3.3 CMK apply + verify

In `terraform.tfvars`: `enable_cmk = true`.
```
scripts/plan_artifact.sh wave4-w3-cmk
make plan     # review: new aws_kms_key + aws_kms_alias, and the S3/RDS/DynamoDB/
              # log-group resources picking up the CMK ARN (in-place update, not replace,
              # except RDS: setting a KMS key on an EXISTING instance forces replacement,
              # confirmed in the module's own doc comment; expect an RDS replace here since
              # harbormaster-base-pg already exists unencrypted-by-CMK)
make apply    # type yes
aws kms list-aliases --region us-east-1 --query "Aliases[?contains(AliasName,'harbormaster')]"
```
Confirm the alias exists and points at a real key ARN. If the RDS replace
gives you pause (a fresh Phase 1 window is the module's own documented
precondition for enabling CMK on RDS painlessly), you can instead apply CMK
with RDS's KMS key left as-is this round and revisit RDS re-encryption in a
dedicated window; note that trade-off in `AB_MASTERCLASS_AUDIT.md` if you take
it. CMK is a standing ~$1/month once enabled: decide whether it stays on
after this window or gets flipped back to `false` at teardown, and record
that decision (a small permanent-cost decision matters more than instructions
in this repo assume by default).

### W3.4 Two-variant canary live shift with a forced revert

Prerequisite: the SageMaker Pi-DPM endpoint exists (Phase 3). If it is not up
from a prior window, bring it up per `PHASE_3_AWS_SHOWCASE.md` Part 2 first
(build the demo checkpoint + demo container, `enable_phase3 = true`, apply).

Plant a candidate variant:
```
# terraform.tfvars: candidate_model_data_url = "s3://<MODELS_BUCKET>/pidpm/us-east-1/demo/model.tar.gz"
# (the same demo checkpoint works as its own "candidate"; a real demo would use a second checkpoint)
scripts/plan_artifact.sh wave4-w3-canary-plant
make apply
aws sagemaker describe-endpoint --region us-east-1 --endpoint-name <endpoint> \
  --query 'ProductionVariants'
```
Confirm two variants, `champion` at weight 1.0 and `candidate` at 0.0 (the
module plants it at 0 by design so a plan stays clean post-ramp).

Drive the actual weight ladder through the real actuator code
(`mlops/canary_actuator.py`), not a raw CLI call, so this exercises the same
path `run_promotion` uses in production:
```
AWS_REGION=us-east-1 .venv/bin/python -c "
import boto3
from mlops.canary_actuator import make_set_canary_weight, make_revert_to_champion

client = boto3.client('sagemaker', region_name='us-east-1')
endpoint = '<endpoint-name-from-terraform-output-pidpm_endpoint_name>'
set_weight = make_set_canary_weight(client, endpoint)
revert = make_revert_to_champion(client, endpoint)

for w in (5, 25, 50, 100):
    set_weight(w)
    print(f'weight={w} set')
    import time; time.sleep(30)  # let CloudWatch/traffic settle before the next step

print('forcing a revert to prove invariant 3 (one call, full weight back to champion)')
revert()
print(client.describe_endpoint(EndpointName=endpoint)['ProductionVariants'])
"
```
Confirm the final `describe_endpoint` shows `champion` back at 1.0 and
`candidate` at 0.0 in one call, matching `docs/phases/PHASE_3.md`'s invariant
3 and `docs/drills/L2_canary_rollback.md`'s local transcript, now proven live.
Write the transcript to `docs/drills/L2_canary_rollback_live.md` in the same
format as the local one (timestamp header, the weight sequence, the final
verdict line), since this is the first time that drill has run against real
AWS.

### W3.5 Capture a final plan artifact, then teardown

```
scripts/plan_artifact.sh wave4-w3-final-state
```
Flip in `terraform.tfvars`: `enable_phase2 = false` (always; MSK is the
$18/day risk). Decide `enable_cmk` per W3.3 above; decide `enable_phase3`
per whether you're continuing the canary drill into W4 (if not, flip it
false too, you can bring the endpoint back up for W4's optional Bedrock/RLS
legs later).
```
scripts/plan_artifact.sh wave4-w3-teardown
make apply    # type yes; NEVER make destroy
```
Verify:
```
aws kafka list-clusters-v2 --region us-east-1 --query 'ClusterInfoList[].ClusterName'
aws ecs list-services --region us-east-1 --cluster harbormaster-base-cluster
```
No MSK cluster; only `harbormaster-base-serving` (and, if you kept Phase 3
up, `harbormaster-base-cdc-connect`/`-consumer` should be gone, `cdc-*`
absent).

---

## Window W4: EKS/KEDA + backpressure + teardown-guard (the phase-gate-closing window)

Budget: EKS control plane ~$0.10/hour flat from creation regardless of node
count (the one cost that doesn't idle to zero, why gate 5.0's teardown guard
exists); node group (spot, scale-to-zero) near-$0 at idle, a few cents/hour
with 1–2 nodes up. A 2–4 hour bounded window: $0.20–3 total, well inside the
$75 cap, provided the teardown guard actually fires (it is armed by default:
`phase5_guard_dry_run` defaults `false`).

### W4.0 Apply #1: EKS cluster + node group + teardown guard

In `terraform.tfvars`:
```
enable_phase1 = true     # already true
enable_phase5 = true
# phase5_teardown_max_age_hours defaults to 4; leave it unless you need longer
# phase5_keep_alive_until stays empty unless you deliberately extend
```
```
scripts/plan_artifact.sh wave4-w4-eks-apply1
make plan    # review: modules/eks_cluster + modules/eks_node_group + modules/eks_teardown_guard's
             # resources; enable_phase5_keda stays false this apply (helm provider not wired yet)
make apply   # type yes; EKS control-plane creation takes 10–15 minutes, be patient
```
Verify:
```
aws eks describe-cluster --region us-east-1 --name harbormaster-base-eks --query 'cluster.status'
aws eks list-nodegroups --region us-east-1 --cluster-name harbormaster-base-eks
```
Expect `ACTIVE` and one node group (likely `desired_size=0` at this point,
scale-to-zero floor per the module).

Confirm the teardown guard is armed and watching, right away (this is the
structural mitigation, verify it exists before anything else):
```
aws events list-rules --region us-east-1 --name-prefix harbormaster-base-eks-teardown
aws lambda get-function --region us-east-1 --function-name harbormaster-base-eks-teardown-guard \
  --query 'Configuration.Environment.Variables'
```
Expect `MAX_AGE_HOURS` = 4 (or whatever you set) and the EventBridge rule
`ENABLED` on its `rate(30 minutes)` schedule.

### W4.1 Apply #2: install KEDA

In `terraform.tfvars`:
```
enable_phase5_keda = true
```
```
scripts/plan_artifact.sh wave4-w4-keda-apply2
make plan    # the helm_release "keda" resource + its data-source reads of the now-existing cluster
make apply
```
Verify:
```
aws eks update-kubeconfig --region us-east-1 --name harbormaster-base-eks
kubectl get pods -n keda
```
Expect the KEDA operator + metrics-server pods `Running`.

### W4.2 Deploy the serving workload + retarget the front door

```
kubectl apply -k deploy/k8s/serving/base
kubectl get scaledobject -A
kubectl get deployment harbormaster-serving -o jsonpath='{.spec.replicas}'
```
Expect the `ScaledObject` present with `minReplicaCount: 0` and the
Deployment starting at 0 replicas (nothing has hit the trigger yet).

Get the Service's internal address (Cloud Map or the Service's cluster DNS,
whichever your `deploy/k8s/serving/base/service.yaml` uses) and retarget
API Gateway:
```
# terraform.tfvars:
serving_target      = "eks"
eks_integration_uri  = "<the Cloud Map service ARN or NLB listener ARN fronting the EKS Service>"
```
```
scripts/plan_artifact.sh wave4-w4-apigw-retarget
make plan    # the proxy route's integration swaps from the ECS Cloud Map target to eks_integration_uri
make apply
```
The ECS `harbormaster-base-serving` service is deliberately NOT deleted this
gate (documented rollback path); both exist, only the route changed.

### W4.3 Measure cold-start: 0 -> N -> 0 (closes criterion a)

With the Deployment sitting at 0 replicas and no traffic:
```
SERVING=$(terraform -chdir=infra/terraform/envs/base output -raw serving_api_endpoint)
START=$(date -u +%s.%N)
curl -s -o /dev/null -w '%{http_code}\n' "$SERVING/healthz"
END=$(date -u +%s.%N)
echo "cold-start latency (approx, includes the KEDA polling interval): $(echo "$END - $START" | bc)s"
```
This first-request number is an *upper bound* (KEDA's default polling
interval adds latency the request itself does not cause); pair it with the
more precise measurement:
```
kubectl get hpa -n default -w   # watch the KEDA-managed HPA go 0->1 in real time, note the wall-clock gap
```
Record BOTH numbers (first-successful-request latency, and the
scale-event-to-ready-pod wall clock from `kubectl get hpa -w` /
`kubectl get pods -w`) in `docs/drills/M3_backpressure_loadtest.md` (created
in W4.4 below); this is the measured cold-start the phase gate needs, not an
estimate. Then let it idle back to 0 (KEDA's `cooldownPeriod`, typically a
few minutes with no traffic) and confirm:
```
kubectl get deployment harbormaster-serving -o jsonpath='{.spec.replicas}'   # back to 0
```

### W4.4 Backpressure drill (closes criterion b)

```
KINESIS_STREAM_NAME=harbormaster-base-ais-raw \
STEADY_RPS=20 BURST_RPS=400 BURST_START_S=60 BURST_END_S=180 RAMP_S=15 \
DURATION_S=300 AWS_REGION=us-east-1 \
.venv/bin/python scripts/loadtest_kinesis_backpressure.py
```
While it runs, in separate terminals watch:
```
kubectl get scaledobject -w                        # trigger firing
kubectl get pods -w                                # 0 -> N replicas
aws cloudwatch get-metric-statistics --region us-east-1 \
  --namespace AWS/Kinesis --metric-name GetRecords.IteratorAgeMilliseconds \
  --dimensions Name=StreamName,Value=harbormaster-base-ais-raw \
  --start-time $(date -u -v-15M +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 --statistics Maximum
```
If Flink (gate 1.5) is applied, also pull its backpressure/watermark-lag
metrics from the Managed Flink application's CloudWatch namespace during the
spike window. Write `docs/drills/M3_backpressure_loadtest.md` matching the
`L1`/`L2` transcript convention already in the repo: a timestamp header,
the burst profile used, the observed IteratorAge peak and time-to-drain, the
KEDA scale event timeline (0 -> N -> back to 0), the two cold-start numbers
from W4.3, and a one-line VERDICT.

### W4.5 Optional: live RLS drill against the real RDS instance

Not gate-required (criterion e is already closed structurally), but if you
want the real-infrastructure version of `docs/drills/M_tenant_leak.md`:
this needs the gate 5.4 `tenant_id` + RLS migration applied to
`harbormaster-base-pg`, which has not happened yet (only the local-Postgres
smoke test has run it). That is a schema migration against your live,
already-populated Phase 1 database, real risk if rushed. If you want this
live leg, treat it as its own reviewed step (confirm the migration is
additive/backward-compatible, `tenant_id` back-compat empty-string
convention per `PHASE_5.md` gate 5.4), not something to fold in casually at
the end of an EKS window.

### W4.6 Optional: live Bedrock calls

Prerequisite: your account needs Bedrock model access granted for whichever
model you use (Bedrock model access is a per-model, console-granted opt-in,
separate from IAM permissions; check the Bedrock console's "Model access"
page first, this is not something `terraform apply` grants).
```
export HM_BEDROCK_MODEL_ID="anthropic.claude-3-5-sonnet-20241022-v2:0"   # or whichever model you've enabled
AWS_REGION=us-east-1 .venv/bin/python -c "
import asyncio
from app.bedrock_explainer import BedrockExplainer
from app.config import Settings

explainer = BedrockExplainer.from_settings(Settings())
print('enabled:', explainer.enabled)
result = asyncio.run(explainer.aexplain(['off_corridor', 'WATCHLIST_HIT'], 0.87))
print(result)
"
```
Confirm `enabled: True` and a real narrative string back, then confirm (per
the locked design) that the prompt-construction function never received raw
lat/lon: this is already asserted in `serving/tests/` against a fake client,
here you're just confirming the real client path also works.

### W4.7 Prove the teardown guard force-destroys the cluster, live (closes criterion f)

Two honest ways to do this, pick one:

**(A) Wait it out.** If `phase5_teardown_max_age_hours = 4` and you've been in
this window that long, just watch:
```
watch -n 60 'aws eks describe-cluster --region us-east-1 --name harbormaster-base-eks --query cluster.status 2>&1'
```
until it errors `ResourceNotFoundException` (cluster gone). Check the
Lambda's CloudWatch log group for its decision trail
(`aws logs tail /aws/lambda/harbormaster-base-eks-teardown-guard --region us-east-1 --follow`).

**(B) Force it now, for the demo.** Temporarily lower the window so the next
scheduled 30-minute tick trips it:
```
scripts/plan_artifact.sh wave4-w4-force-teardown-demo
# terraform.tfvars: phase5_teardown_max_age_hours = 0
make apply
aws logs tail /aws/lambda/harbormaster-base-eks-teardown-guard --region us-east-1 --since 35m --follow
```
Within one EventBridge tick (up to 30 minutes, or invoke the Lambda directly
for an immediate proof: `aws lambda invoke --region us-east-1 --function-name
harbormaster-base-eks-teardown-guard /tmp/out.json && cat /tmp/out.json`),
confirm the log shows a real decision to destroy and the node group / cluster
actually disappear:
```
aws eks list-nodegroups --region us-east-1 --cluster-name harbormaster-base-eks 2>&1
aws eks describe-cluster --region us-east-1 --name harbormaster-base-eks 2>&1
```
Either way, this live fire is the (f) proof and also the moment war story P37
("cold-start SLA breach, ANTICIPATED") either gets grounded (if a tier's SLO
actually breached during W4.4) or stays anticipated (if it didn't); log
whichever happened honestly in `PLATFORM_WAR_STORIES.md`.

### W4.8 Reconcile Terraform state after the live force-destroy

The guard deletes AWS resources outside Terraform's own apply, so state now
disagrees with reality. Reconcile before the next apply touches Phase 5:
```
# after confirming AWS-side deletion above:
terraform -chdir=infra/terraform/envs/base state list | grep -E 'eks_cluster|eks_node_group'
terraform -chdir=infra/terraform/envs/base state rm 'module.eks_cluster[0].aws_eks_cluster.this' \
  'module.eks_node_group[0].aws_eks_node_group.this'   # exact addresses from state list above
```
Then set `enable_phase5 = false`, `enable_phase5_keda = false`,
`serving_target = "ecs"`, `eks_integration_uri = ""` and:
```
scripts/plan_artifact.sh wave4-w4-final-teardown
make plan     # should now show a clean removal of anything the guard didn't already take (teardown guard
              # module itself, apigw retarget) with ZERO stale eks_cluster/eks_node_group diffs
make apply
```

### W4.9 Full verification: back to Phase-0/1-only standing

```
aws eks list-clusters --region us-east-1
aws kafka list-clusters-v2 --region us-east-1 --query 'ClusterInfoList[].ClusterName'
aws sagemaker list-endpoints --region us-east-1 --query 'Endpoints[].EndpointName'
scripts/plan_artifact.sh wave4-w4-verified-clean
```
Expect: no EKS clusters, no MSK clusters, no SageMaker endpoints (unless you
deliberately kept Phase 3 up), and the final plan artifact showing the
platform back at whatever standing state you intend to leave it in (Phase
0/1-only, or Phase 0/1 + CMK if you kept that from W3.3).

---

## After both windows

1. Update `docs/phases/PHASE_5.md`'s status line: gates 5.-1..5.9 built AND
   the phase gate CLOSED, with the three measured numbers (cold-start
   latency, backpressure postmortem summary, teardown-guard live-fire
   timestamp) replacing the "pending W4" language.
2. Append the grounded war stories to `PLATFORM_WAR_STORIES.md` (P37 cold-start,
   graduated from ANTICIPATED to grounded either way; a new entry if the live
   RLS or Bedrock legs surfaced anything).
3. Commit `docs/drills/M3_backpressure_loadtest.md`, any
   `docs/drills/L2_canary_rollback_live.md`, the `docs/plan-artifacts/`
   files this window generated, and the doc updates, on a short-lived branch
   (`feat/wave4-live-validation` or similar), PR, merge same day (the
   standing "close the branching" rule).
4. That merge is the trigger for Wave 5: superseding
   `sessions/CODEX_HANDOFF_2026-07-11.md` with the final production
   handoff.
