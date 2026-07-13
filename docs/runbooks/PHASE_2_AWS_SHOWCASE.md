# Runbook: Phase 2 AWS showcase (Arun-run demo apply)

The AWS plane of the CDC pipeline, run only inside a demo window. Everything
here is behind `enable_phase2` (plus `enable_phase1`); teardown is a tfvars
flip, never `make destroy`. Local acceptance already passed in full
(`docs/drills/E2E_local_stack.md`); this showcase proves the same pipeline on
RDS + MSK Serverless + Fargate.

COST: MSK Serverless is ~$0.75/cluster-hour (~$18/day if forgotten). A 3-hour
demo lands around $3-4 total. The nightly teardown Lambda sweeps MSK as a
backstop and alerts go to arunshar@umn.edu, but the discipline is: apply at
the start of the window, flip back at the end, verify in the console.

Prereqs: Docker running; AWS CLI as arn-admin with `--region us-east-1`
(the CLI default is us-west-2; every command below pins the region); repo
`~/code/harbormaster`; `make plan` reviewed before every apply.

## 1. Package the slot-lag Lambda

```
cd ~/code/harbormaster
make cdc-lambda-package
```

Terraform archives `infra/lambda/cdc_slot_lag/build/` via the archive
provider; the apply fails if this step is skipped.

## 2. First apply: infrastructure + ECR repos (no images yet)

In `infra/terraform/envs/base/terraform.tfvars` set:

```
enable_phase1 = true
enable_phase2 = true
```

Leave `cdc_connect_image` / `cdc_consumer_image` unset (empty): the connect
and consumer ECS services are additionally gated on the image vars, so this
first apply creates everything else, including the two ECR repos
(push-then-apply, the review-fix ordering).

```
make plan    # expect 67 add / 0 change / 0 destroy from a phase1-only base
make apply   # type yes
```

## 3. Build and push both images

Fargate here runs LINUX/X86_64; on the M-series Mac build with an explicit
platform or the tasks die on exec format:

```
cd ~/code/harbormaster
AWS_REGION=us-east-1
CONNECT_REPO=$(terraform -chdir=infra/terraform/envs/base output -raw cdc_connect_ecr_repository_url)
CONSUMER_REPO=$(terraform -chdir=infra/terraform/envs/base output -raw cdc_consumer_ecr_repository_url)

aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin "${CONNECT_REPO%%/*}"

docker build --platform linux/amd64 -f cdc/connect/Dockerfile -t "$CONNECT_REPO:demo" .
docker push "$CONNECT_REPO:demo"

docker build --platform linux/amd64 -f cdc/consumer/Dockerfile -t "$CONSUMER_REPO:demo" .
docker push "$CONSUMER_REPO:demo"
```

## 4. Second apply: the two services

Add to `terraform.tfvars` (full URIs with the `:demo` tag):

```
cdc_connect_image  = "<CONNECT_REPO>:demo"
cdc_consumer_image = "<CONSUMER_REPO>:demo"
```

```
make plan    # only the connect + consumer services and their IAM/log groups
make apply   # type yes
```

Wait for both services to reach steady state:

```
aws ecs wait services-stable --region us-east-1 \
  --cluster harbormaster-base-cluster \
  --services harbormaster-base-cdc-connect harbormaster-base-cdc-consumer
```

## 5. Register the connector (in-VPC, via ECS exec)

Connect REST (8083) is in-VPC only, and the RDS password never leaves the
task: the config references `${dir:/dev/shm/secrets:password}` through the
DirectoryConfigProvider. The task entrypoint writes the ECS-injected secret to
that tmpfs file before Connect starts. Generate a base64 transport command
locally, then run it inside the container. Base64 is required here because an
unquoted heredoc expands `${dir:...}` in Bash before curl can send it.

```
cd ~/code/harbormaster
RDS_HOST=$(terraform -chdir=infra/terraform/envs/base output -raw rds_endpoint | cut -d: -f1)
CONNECTOR_COMMAND=$(RDS_HOST="$RDS_HOST" .venv/bin/python -c '
import os
from cdc.connector.config import build_connector_config
from cdc.connector.registration import build_ecs_exec_registration_command

body = build_connector_config(db_host=os.environ["RDS_HOST"], db_port=5432)
print(build_ecs_exec_registration_command(body))
')

TASK_ARN=$(aws ecs list-tasks --region us-east-1 \
  --cluster harbormaster-base-cluster \
  --service-name harbormaster-base-cdc-connect \
  --query 'taskArns[0]' --output text)

aws ecs execute-command --region us-east-1 \
  --cluster harbormaster-base-cluster --task "$TASK_ARN" \
  --container connect --interactive \
  --command "$CONNECTOR_COMMAND"
```

Poll until the connector and every task are `RUNNING`. The generated command is
bounded, waits through transitional states, and exits nonzero on `FAILED` or
timeout:

```
STATUS_COMMAND=$(.venv/bin/python -c '
from cdc.connector.registration import build_ecs_exec_readiness_command

print(build_ecs_exec_readiness_command())
')

aws ecs execute-command --region us-east-1 \
  --cluster harbormaster-base-cluster --task "$TASK_ARN" \
  --container connect --interactive \
  --command "$STATUS_COMMAND"
```

## 6. The five acceptance criteria on AWS

RDS and MSK are not reachable from the laptop (private by design), so the
pytest e2e's Kafka/Postgres criteria run through in-VPC primitives instead.
Set up once:

```
SERVING=$(terraform -chdir=infra/terraform/envs/base output -raw serving_api_endpoint)
TABLE=$(terraform -chdir=infra/terraform/envs/base output -raw feast_online_table_name)
MMSI=368200099
```

(a) Flag-to-scored within ~5 s, from the laptop:

```
time (curl -s -X PUT "$SERVING/v1/registry/watchlist/$MMSI" \
  -H 'Content-Type: application/json' \
  -d '{"reason": "aws showcase", "severity": 0.9, "added_by": "arun"}' && \
  until aws dynamodb get-item --region us-east-1 --table-name "$TABLE" \
    --key "{\"entity_id\":{\"S\":\"$MMSI\"},\"feature_name\":{\"S\":\"watchlist\"}}" \
    --query 'Item.last_applied_lsn' --output text | grep -qv None; do sleep 0.5; done)
```

Then score an AIS event for that MMSI via `POST $SERVING/v1/score-ais` and
confirm WATCHLIST_HIT in the reasons.

(b) Replay produces no duplicate online state: hash the online items, run a
one-off consumer task with a FRESH group (reads from earliest), re-hash.

```
aws dynamodb scan --region us-east-1 --table-name "$TABLE" --consistent-read \
  --output json | python3 -c "import sys,json,hashlib; d=json.load(sys.stdin); \
items=sorted(json.dumps(i,sort_keys=True) for i in d['Items']); \
print(hashlib.sha256('\n'.join(items).encode()).hexdigest())"
```

```
TASKDEF=$(aws ecs describe-services --region us-east-1 \
  --cluster harbormaster-base-cluster --services harbormaster-base-cdc-consumer \
  --query 'services[0].taskDefinition' --output text)
NETCFG=$(aws ecs describe-services --region us-east-1 \
  --cluster harbormaster-base-cluster --services harbormaster-base-cdc-consumer \
  --query 'services[0].networkConfiguration' --output json)
aws ecs run-task --region us-east-1 --cluster harbormaster-base-cluster \
  --task-definition "$TASKDEF" --launch-type FARGATE \
  --network-configuration "$NETCFG" \
  --overrides '{"containerOverrides":[{"name":"cdc-consumer","environment":[{"name":"HM_KAFKA_GROUP","value":"hm-cdc-replay-demo"}]}]}'
```

Give it a minute to drain the topics (watch its log stream), stop the task,
re-run the scan hash: IDENTICAL is the pass. The Iceberg `cdc_audit` table
grew applied=false rows meanwhile (Athena: transport truth vs state truth).

(c) Debezium restart loses no change: write a few registry PUTs, force a new
connect deployment mid-stream, confirm every row lands online.

```
aws ecs update-service --region us-east-1 --cluster harbormaster-base-cluster \
  --service harbormaster-base-cdc-connect --force-new-deployment
aws ecs wait services-stable --region us-east-1 \
  --cluster harbormaster-base-cluster --services harbormaster-base-cdc-connect
```

The replication slot holds the position; re-check each PUT MMSI with the
(a)-style get-item loop.

(d) Delete removes the vessel from the online watchlist:

```
curl -s -X DELETE "$SERVING/v1/registry/watchlist/$MMSI"
aws dynamodb get-item --region us-east-1 --table-name "$TABLE" \
  --key "{\"entity_id\":{\"S\":\"$MMSI\"},\"feature_name\":{\"S\":\"watchlist\"}}" \
  --query 'Item.deleted' --output text   # expect a true soft-delete marker
```

Score the MMSI again: WATCHLIST_HIT is gone.

(e) Slot-lag alarm fires for a stalled consumer: scale the consumer to 0,
keep a trickle of registry PUTs going, and watch the CloudWatch alarm (the
1-minute Lambda publishes ReplicationSlotLagBytes; missing data breaches).

```
aws ecs update-service --region us-east-1 --cluster harbormaster-base-cluster \
  --service harbormaster-base-cdc-consumer --desired-count 0
watch -n 30 aws cloudwatch describe-alarms --region us-east-1 \
  --alarm-names harbormaster-base-cdc-slot-lag \
  --query 'MetricAlarms[0].StateValue'
```

ALARM is the pass (FinOps SNS emails arunshar@umn.edu). Scale back to 1,
watch the lag drain and the alarm return to OK; that recovery IS war story
P9's fix demonstrated on real infrastructure.

## 7. Teardown (END OF DEMO WINDOW, always)

Flip in `terraform.tfvars` (leave the image vars; they are inert once the
toggle is off):

```
enable_phase2 = false
```

```
make plan    # destroys only Phase 2 resources; Phase 0/1 untouched
make apply   # type yes
```

Then verify, all three:

```
aws kafka list-clusters-v2 --region us-east-1 --query 'ClusterInfoList[].ClusterName'
aws ecs list-services --region us-east-1 --cluster harbormaster-base-cluster
aws cloudwatch describe-alarms --region us-east-1 --alarm-name-prefix harbormaster-base-cdc
```

No MSK cluster, no cdc-* services, no cdc alarm. NEVER `make destroy` (it
would take Phase 0/1 state with it). If Phase 1 should also come down, flip
`enable_phase1` the same way in a separate reviewed plan.
