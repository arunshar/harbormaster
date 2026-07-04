# Runbook: sprint window W1 (Phases 0 + 1 + 2 AWS showcase, ~90 min)

The first of the two Arun-run demo windows from the 24-hour completion
sprint. One sitting proves: the Phase 0 guardrail path (teardown Lambda
dry run), the first-ever live Phase 1 e2e (gate G8), and the Phase 2 CDC
showcase on real RDS + MSK + Fargate. This runbook orchestrates; the
Phase 2 detail stays in `PHASE_2_AWS_SHOWCASE.md` (do not duplicate it).

Ground rules, unchanged: account 645322802947, us-east-1 on every
command; `make apply` reads its plan before typing yes; NEVER
`make destroy`; MSK Serverless is ~$18/day idle, so Phase 2 tears down
before the window closes, no exceptions.

## Part 0: pre-window prep (Claude-side; Arun only confirms two things)

Claude runs before the window opens:

```
cd ~/code/harbormaster
make serve-docker                                  # serving image, local tag
docker build -f streaming/ingestor/Dockerfile -t harbormaster-ingestor:dev .
make flink-package                                 # dist/flink-app.zip
make cdc-lambda-package                            # slot-lag Lambda build dir
```

Arun confirms (2 min, any time before the window): (a) Docker Desktop is
running; (b) the AWS budget email at arunshar@umn.edu shows no surprises
(current month reads $0.00 as of the 2026-07-04 audit).

Expected plan-shape note (recorded so nobody stops the window to
investigate): the first `make plan` shows the 2-to-change finops Lambda
drift from commit `f89e12b` alongside Phase 1's adds. Expected; it
resolves on this very apply.

## Part 1: Phase 0 guardrail proof (~5 min)

The one Phase 0 item never evidenced (AWS_SETUP.md step 5): prove the
teardown Lambda end to end in dry-run.

DRY_RUN is the Lambda's ENVIRONMENT variable, not a payload key
(`infra/lambda/teardown/handler.py`: unset or "true" logs intended
actions and changes nothing), and it is already "true" via
`teardown_dry_run = true` in tfvars, so a plain invoke IS the dry run:

```
aws lambda invoke --region us-east-1 \
  --function-name harbormaster-base-teardown \
  /tmp/teardown_out.json
cat /tmp/teardown_out.json
```

Pass: exit 0 and the SNS summary email arrives at arunshar@umn.edu.
Consciously deferred, on record: the deliberate budget-breach test (it
would attach the IAM-deny policy to the platform role mid-sprint and
block every apply that follows). It stays an open Phase 0 item.

## Part 2: Phase 1 apply + images + Flink + first-ever live e2e (~45 min)

1. In `infra/terraform/envs/base/terraform.tfvars`: `enable_phase1 = true`.
2. `make plan` (expect ~44 add / 2 change / 0 destroy, the 2-change being
   the drift note above) then `make apply`, type yes.
3. Push both images (repo URLs exist only after the apply):

```
AWS_REGION=us-east-1
SERVING_REPO=$(terraform -chdir=infra/terraform/envs/base output -raw serving_ecr_repository_url)
INGESTOR_REPO=$(terraform -chdir=infra/terraform/envs/base output -raw ingestor_ecr_repository_url)
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin "${SERVING_REPO%%/*}"
docker tag harbormaster-serving:dev  "$SERVING_REPO:latest"  && docker push "$SERVING_REPO:latest"
docker tag harbormaster-ingestor:dev "$INGESTOR_REPO:latest" && docker push "$INGESTOR_REPO:latest"
aws ecs update-service --region us-east-1 \
  --cluster harbormaster-base-cluster \
  --service harbormaster-base-serving --force-new-deployment
```

4. Flink job:

```
MODELS_BUCKET=$(terraform -chdir=infra/terraform/envs/base output -raw models_bucket_name)
aws s3 cp dist/flink-app.zip "s3://${MODELS_BUCKET}/flink/flink-app.zip" --region us-east-1
```

   Set `flink_code_s3_key = "flink/flink-app.zip"` in tfvars; `make plan`
   (expect the KDA Flink app to add) then `make apply`.

5. Run the replay ingestor over the fixture (one-off Fargate task run,
   MODE=REPLAY is the task definition's default):

```
aws ecs run-task --region us-east-1 \
  --cluster harbormaster-base-cluster \
  --task-definition $(terraform -chdir=infra/terraform/envs/base output -raw ingestor_task_definition_arn) \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$(terraform -chdir=infra/terraform/envs/base output -json public_subnet_ids | jq -r 'join(",")')],assignPublicIp=ENABLED}"
```

6. Gate G8, the Phase 1 phase gate, never before run live:

```
SERVING_URL=$(terraform -chdir=infra/terraform/envs/base output -raw serving_api_endpoint) \
HM_E2E=1 make e2e
```

7. Evidence capture (feeds Block E's honest resume numbers): the e2e
   latency figures from the test output, the CloudWatch dashboard
   (`harbormaster-base-phase1`) p95 panel screenshot, one scored
   response JSON. Transcript lands in `docs/drills/` at closeout.

8. Optional gate G9 if the AISStream.io key is at hand: flip the
   ingestor task's `AIS_LIVE=1` for one short run, watch a real fix
   score end to end, flip back. Skipped-and-documented is fine.

## Part 3: Phase 2 CDC showcase (~30 min, then MANDATORY teardown)

Follow `docs/runbooks/PHASE_2_AWS_SHOWCASE.md` steps 1-7 as written
(package Lambda -> first apply `enable_phase2 = true` -> push connect +
consumer images -> second apply with image vars -> register the Debezium
connector via ECS exec -> run the five acceptance criteria -> teardown).
W1-specific notes only:

- The five criteria transcripts are the Phase 2 completion evidence;
  capture them into `docs/drills/` like the local-stack run was.
- War-story opportunities: P1-P8 are still "anticipated"; anything that
  breaks here graduates one of them with a real artifact. Take the
  artifact (log excerpt, event JSON) the moment it happens.
- Before leaving Part 3, no matter what: `enable_phase2 = false`,
  `make apply`, then verify MSK is gone:

```
aws kafka list-clusters-v2 --region us-east-1 --query 'ClusterInfoList[].ClusterName'
```

## Part 4: end-of-window state (~5 min)

- `enable_phase2 = false` applied (verified above).
- `enable_phase1` STAYS true only if W2 (the Phase 3 showcase) happens
  within a few hours; otherwise flip it false and `make apply` before
  leaving (Phase 1 idles at real cost: RDS free-tier hours, Fargate
  tasks, Kinesis on-demand).
- Push any tfvars-adjacent commits (runbook edits, drill transcripts,
  war stories) to `phase3-lake`.
- Note the wall-clock spend estimate against the $75 cap in the session
  handoff (expected: $3-8 for the whole window).
