# Runbook: Phase 3 AWS showcase (Arun-run demo apply)

The AWS plane of the lake + promotion pipeline, run only inside a demo
window. Everything here is behind `enable_phase3` (plus `enable_phase1`);
teardown is a tfvars flip, never `make destroy`. `make lake-e2e` already
proved all five acceptance criteria against pure functions and fakes; this
showcase proves the same logic against real EMR, real SageMaker, and a
real S3-backed promotion run.

**Honest scope note, read this first.** `mlops/pidpm_container/server.py`
(the "real" container wrapping pi-grpo's `PiDpmScorer`) is illustrative
only: it needs pi-grpo's scorer code from a separate, un-vendored repo, and
there is no real MSI-trained Pi-DPM checkpoint yet. Part 2 below deploys
`mlops/pidpm_container/demo/` instead, a real, tested, buildable stand-in
using the exact toy scorer already exercised in
`scripts/drill_l1_training_serving_skew.py`. Every response it returns
says `"model": "phase3-demo-standin"`; it demonstrates the real
infrastructure (async endpoint, scale-to-zero, the promotion pipeline),
never a real trained model's quality. When a real checkpoint exists (MSI
training + `scripts/export_checkpoint.sh`, gate 3.4) and the real container
is built (vendoring pi-grpo, gate 3.6), swap the image/model_data_url vars
in Part 2 for the real ones; nothing else in this runbook changes.

COST: EMR Serverless is pay-per-second with no idle cluster (Part 1 costs
well under $1 for the fixture-scale backfill below). The SageMaker async
endpoint scales to zero between invocations (application auto-scaling
`min_capacity=0`); a demo window with a handful of invocations is a few
dollars at most. Watch two things: an EMR job created without its
structural auto-terminate (should be impossible, `emr_module_has_auto_terminate`
asserts this at the code level, but verify in the console anyway) and the
SageMaker endpoint's auto-scaling actually reaching 0 after the window (the
two budget threats named in `docs/phases/PHASE_3.md`'s cost envelope).

Prereqs: Docker running (for Part 2 only; Part 1 needs no image); AWS CLI
as arn-admin with `--region us-east-1` (the CLI default is us-west-2; every
command below pins the region); repo `~/code/harbormaster`; `make plan`
reviewed before every apply.

## Part 1: the transient EMR backfill

### 1.1 Upload a raw extract fixture to S3

Reuse the committed lake fixture (already GE-suite-clean, per gate 3.1) as
the "raw extract" EMR reads; a real backfill would point at a real
MarineCadastre S3 prefix instead.

```
cd ~/code/harbormaster
LAKE_BUCKET=$(terraform -chdir=infra/terraform/envs/base output -raw lake_bucket_name)
.venv/bin/python -c "
import json
from pathlib import Path
rows = [json.loads(l) for l in Path('lake/fixtures/marinecadastre_sample.jsonl').read_text().splitlines() if l.strip()]
import pandas as pd
pd.DataFrame(rows).to_parquet('/tmp/marinecadastre_raw.parquet')
"
aws s3 cp /tmp/marinecadastre_raw.parquet \
  "s3://${LAKE_BUCKET}/raw/marinecadastre/marinecadastre_raw.parquet" --region us-east-1
```

### 1.2 First apply: enable_phase3, no image vars needed yet

In `infra/terraform/envs/base/terraform.tfvars` set:

```
enable_phase1 = true
enable_phase3 = true
```

Leave `pidpm_image` / `pidpm_model_data_url` unset (empty): `modules/sagemaker_pidpm`
is additionally gated on both image vars, so this first apply creates the
EMR Serverless application and its IAM role only, not the SageMaker model.

```
make plan    # expect the emr_backfill module's 4 resources (application, IAM role + policy, log group)
make apply   # type yes
```

### 1.3 Submit the (transient) EMR job

No Terraform resource for the job itself (deliberate, gate 3.2): submit it
directly via the CLI, Arun-run.

```
APP_ID=$(terraform -chdir=infra/terraform/envs/base output -raw emr_backfill_application_id)
ROLE_ARN=$(terraform -chdir=infra/terraform/envs/base output -raw emr_backfill_execution_role_arn)
LAKE_BUCKET=$(terraform -chdir=infra/terraform/envs/base output -raw lake_bucket_name)

aws emr-serverless start-job-run --region us-east-1 \
  --application-id "$APP_ID" \
  --execution-role-arn "$ROLE_ARN" \
  --name hm-lake-backfill-demo \
  --job-driver '{
    "sparkSubmit": {
      "entryPoint": "s3://'"$LAKE_BUCKET"'/code/lake_backfill_job.py",
      "entryPointArguments": [
        "s3://'"$LAKE_BUCKET"'/raw/marinecadastre/marinecadastre_raw.parquet",
        "glue",
        "s3://'"$LAKE_BUCKET"'/iceberg"
      ]
    }
  }'
```

(`lake/backfill/job.py` needs to be uploaded to `s3://$LAKE_BUCKET/code/` as
its own step, along with a PySpark-compatible packaging of `lake/` and its
`lake` extra dependencies; scripted the same way `make flink-package` zips
`streaming/flink` for Managed Flink. Not yet scripted here, since gate 3.2's
finding was that this Mac cannot exercise PySpark locally to validate the
packaging step; write the packaging script at demo time against the real
EMR Serverless Spark version.)

### 1.4 Watch it run, then verify in Athena

```
aws emr-serverless get-job-run --region us-east-1 \
  --application-id "$APP_ID" --job-run-id <job-run-id-from-the-start-job-run-response>
```

Once `SUCCESS`, query the Iceberg tables via Athena (Glue catalog `hm`):

```sql
SELECT count(*) FROM hm.ais_history;
SELECT count(*) FROM hm.corridor_graph_nodes;
SELECT count(*) FROM hm.corridor_graph_edges;
```

Confirm a bad-data fixture (an out-of-range MMSI row, matching
`tests/e2e/test_phase3.py`'s criterion (a)) submitted the same way produces
a FAILED job run with no rows written, not a partial/silent write.

### 1.5 Confirm auto-terminate

```
aws emrserverless get-application --region us-east-1 --application-id "$APP_ID" \
  --query 'application.autoStopConfiguration'
```

Expect `{"enabled": true, "idleTimeoutMinutes": 15}`. Leave the application
running (it costs nothing idle); there is no "job" to tear down since none
is a standing resource.

## Part 2: the SageMaker demo-standin endpoint + promotion pipeline

### 2.1 Build the demo checkpoint and the demo container image

```
cd ~/code/harbormaster
make pidpm-demo-checkpoint   # writes dist/demo_pidpm_checkpoint/model.tar.gz

MODELS_BUCKET=$(terraform -chdir=infra/terraform/envs/base output -raw models_bucket_name)
aws s3 cp dist/demo_pidpm_checkpoint/model.tar.gz \
  "s3://${MODELS_BUCKET}/pidpm/us-east-1/demo/model.tar.gz" --region us-east-1

AWS_REGION=us-east-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr create-repository --region us-east-1 --repository-name hm-pidpm-demo 2>/dev/null || true
PIDPM_REPO="${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/hm-pidpm-demo"

aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin "$PIDPM_REPO"
docker build --platform linux/amd64 -f mlops/pidpm_container/demo/Dockerfile \
  -t "$PIDPM_REPO:demo" mlops/pidpm_container/demo
docker push "$PIDPM_REPO:demo"
```

### 2.2 Second apply: the SageMaker model + async endpoint

Add to `terraform.tfvars`:

```
pidpm_image           = "<ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/hm-pidpm-demo:demo"
pidpm_model_data_url  = "s3://<MODELS_BUCKET>/pidpm/us-east-1/demo/model.tar.gz"
```

```
make plan    # expect the sagemaker_pidpm module's 9 resources
make apply   # type yes; RDS-scale patience is not needed here, SageMaker model/endpoint stand-up is faster
```

### 2.3 Confirm the endpoint and invoke it once (async)

```
ENDPOINT=$(terraform -chdir=infra/terraform/envs/base output -raw pidpm_endpoint_name)
aws sagemaker describe-endpoint --region us-east-1 --endpoint-name "$ENDPOINT" --query 'EndpointStatus'
```

Expect `InService`. Point `serving`'s settings at it and invoke through the
real `PiDpmClient` (gate 3.6), not a raw AWS CLI call, so this exercises
the actual client code path:

```
HM_PIDPM_ENDPOINT="$ENDPOINT" HM_PIDPM_INPUT_BUCKET="$MODELS_BUCKET" AWS_REGION=us-east-1 \
.venv/bin/python -c "
import asyncio
from app.pidpm_client import PiDpmClient
from app.config import Settings

client = PiDpmClient.from_settings(Settings(pidpm_endpoint='$ENDPOINT', pidpm_input_bucket='$MODELS_BUCKET'))
score = asyncio.run(client.ascore([[40.30, -74.15], [40.32, -74.14]]))
print('score:', score)
"
```

A real number back (not `None`) is the pass; `None` means the client fell
back to the analytic estimate (check `hm_pidpm_lookup_errors_total` and the
endpoint's CloudWatch logs).

### 2.4 Confirm scale-to-zero

Leave the endpoint idle for the auto-scaling target-tracking window (or
force it by directly setting desired capacity, for demo speed):

```
aws application-autoscaling describe-scaling-activities --region us-east-1 \
  --service-namespace sagemaker \
  --resource-id "endpoint/${ENDPOINT}/variant/champion"
```

Watch `DesiredInstanceCount` reach 0 with no invocations; a fresh
invocation afterward should trigger the `HasBacklogWithoutCapacity` alarm
-> the step-scaling policy -> a scale from 0 to 1 (the AWS-documented
two-part pattern gate 3.6 verified against the real provider schema).

### 2.5 Run the real promotion pipeline against this endpoint

This is the part that proves `mlops/promote.py`'s state machine end to end
on real infrastructure, not fakes. Construct a real
`SageMakerModelRegistryClient` and real `boto3` `application-autoscaling`
weight-setter, then call `mlops.promote.run_promotion` exactly as
`tests/e2e/test_phase3.py` does with fakes, swapping in:

- `holdout_result`: run `mlops.holdout_gate.run_holdout_gate` against a
  small labeled batch scored through the demo endpoint (labels can be
  synthetic here, same as the drills; a real run would use the gate 3.3
  training-set export's held-out split).
- `shadow_result`: since this demo has only one endpoint variant, simulate
  the shadow comparison by scoring the same batch twice and asserting
  `score_diff` passes (the demo stand-in is deterministic, so this is
  trivially clean; a real shadow run needs a second `ProductionVariant` in
  `modules/sagemaker_pidpm`, not built in this sketch-to-showcase pass).
- `set_canary_weight`: `aws sagemaker update-endpoint-weights-and-capacities`
  against the real endpoint's variant.
- `revert_to_champion`: the same call, reverting to the prior weight.

Confirm the transition sequence printed matches the pinned clean-run
sequence in `mlops/fixtures/expectations.json`.

## Part 3: teardown (END OF DEMO WINDOW, always)

Flip in `terraform.tfvars` (leave the image vars; they are inert once the
toggle is off):

```
enable_phase3 = false
```

```
make plan    # destroys only Phase 3 resources; Phase 0/1 untouched
make apply   # type yes
```

Then verify:

```
aws sagemaker list-endpoints --region us-east-1 --query 'Endpoints[?contains(EndpointName, `pidpm`)]'
aws emrserverless list-applications --region us-east-1 --query 'applications[?contains(name, `lake-backfill`)]'
```

No SageMaker endpoint, and the EMR Serverless application either gone or
`STOPPED`/idle (it costs nothing idle either way, but flipping the toggle
removes it entirely). NEVER `make destroy` (it would take Phase 0/1/2
state with it). Also delete the demo ECR repo and image if not reusing them
for a future demo:

```
aws ecr delete-repository --region us-east-1 --repository-name hm-pidpm-demo --force
```
