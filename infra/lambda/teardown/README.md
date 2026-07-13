# Harbormaster nightly teardown Lambda

A FinOps guardrail for **Harbormaster**, a production-grade maritime
anomaly-detection platform (a personal project by Arun Sharma, GitHub
`arunshar`). Harbormaster is a clearly-labeled personal extension of work
originally shipped at ESRI (Summer 2023, real company, team, and clients, where
the original maritime detector and AWS MLOps were built). The two are never
merged. This Lambda exists so a forgotten demo cluster cannot quietly run up the
bill: guardrails before any spend.

This function runs on a nightly EventBridge schedule and quiesces or removes the
cost-heavy, tag-scoped resources that are easy to leave running, then reports
month-to-date spend to SNS.

## What it does

For every resource tagged `Project=<PROJECT_TAG>` (default `harbormaster`), the
handler works defensively and one service at a time. W4 network mutations also
require the exact `Environment=<ENVIRONMENT>` and owner `Module` tags.

1. Stops any RUNNING Amazon Managed Service for Apache Flink
   (`kinesisanalyticsv2`) applications.
2. Terminates orphaned EMR clusters in an active state (STARTING,
   BOOTSTRAPPING, RUNNING, WAITING).
3. Deletes MSK Serverless clusters (MSK has no stop; the serverless variant
   bills while it exists, so teardown is a delete).
4. Sets any tagged Auto Scaling Group's desired capacity (and min size) to 0,
   draining instances while keeping the ASG definition for the next bring-up.
5. Requests deletion of scoped Network Load Balancers owned by the
   `eks_frontdoor` module.
6. Requests deletion of scoped NAT gateways and release of scoped Elastic IPs
   once they are unattached. A NAT gateway deletion is asynchronous, so its
   Elastic IP can be released by the next nightly run.
7. Queries Cost Explorer for unblended month-to-date spend.
8. Publishes a single human-readable summary to the SNS topic in
   `ALERT_TOPIC_ARN`.

Each service runs inside its own `try/except`, so a failure in one service
(throttling, a permissions gap, an API outage) never aborts the rest of the
run. Per-service errors are logged as structured records and surfaced in the SNS
summary.

This is intentionally narrow. It tears down compute, streaming, and the
project-tagged W4 network resources that incur hourly charges. It does not
delete state stores (S3, DynamoDB), VPCs, subnets, route tables, or the FinOps
stack itself. Those remain managed by Terraform under `infra/terraform/`.

## Environment variables

| Variable          | Default         | Purpose                                                                 |
| ----------------- | --------------- | ----------------------------------------------------------------------- |
| `DRY_RUN`         | `true`          | When true (or unset), logs intended actions and changes nothing. Set to `false` to act. Any value other than `false`/`0`/`no`/`off` is treated as true so a typo stays safe. |
| `ALERT_TOPIC_ARN` | (unset)         | SNS topic ARN that receives the spend and teardown summary. If unset, the summary is logged only. |
| `PROJECT_TAG`     | `harbormaster`  | Tag value that scopes every action. Only resources tagged `Project=<this>` are touched. |
| `ENVIRONMENT`     | `base`          | Environment tag required for W4 network cleanup. Terraform passes the active environment. |
| `AWS_REGION`      | (runtime)       | Supplied by the Lambda runtime and used implicitly by boto3. Cost Explorer is always queried in `us-east-1`. |

## How it is invoked

An EventBridge (CloudWatch Events) rule fires the function nightly, for example
a daily schedule at 06:00 UTC:

```
cron(0 6 * * ? *)
```

The event payload is not used for control flow; the function logs it and runs
the full sweep. Recommended rollout: deploy with `DRY_RUN=true`, confirm the
EventBridge invocation and the SNS summary look right for a few nights, then
flip `DRY_RUN=false`.

### IAM permissions the execution role needs

Read plus the specific teardown verbs, scoped as tightly as your account allows:

- `kinesisanalytics:ListApplications`, `kinesisanalytics:ListTagsForResource`,
  `kinesisanalytics:StopApplication`
- `elasticmapreduce:ListClusters`, `elasticmapreduce:DescribeCluster`,
  `elasticmapreduce:TerminateJobFlows`
- `kafka:ListClustersV2`, `kafka:ListTagsForResource`, `kafka:DeleteCluster`
- `autoscaling:DescribeAutoScalingGroups`,
  `autoscaling:UpdateAutoScalingGroup`
- `elasticloadbalancing:DescribeLoadBalancers`,
  `elasticloadbalancing:DescribeTags`,
  `elasticloadbalancing:DeleteLoadBalancer`
- `ec2:DescribeNatGateways`, `ec2:DeleteNatGateway`,
  `ec2:DescribeAddresses`, `ec2:ReleaseAddress`
- `ce:GetCostAndUsage`
- `sns:Publish` on the alert topic
- the standard CloudWatch Logs write permissions

## Dependencies

`boto3` only, which is present in the Lambda Python runtime. Nothing is bundled
into the deployment package. `requirements.txt` pins boto3 for local testing
convenience.

## How to test locally

No AWS credentials are required. The tests monkeypatch `boto3.client` with fake
clients that return canned responses.

With pytest:

```bash
cd infra/lambda/teardown
python -m pytest test_handler.py -v
```

Without pytest (built-in fallback runner):

```bash
cd infra/lambda/teardown
python test_handler.py
```

Compile check:

```bash
python -m py_compile infra/lambda/teardown/handler.py \
                     infra/lambda/teardown/test_handler.py
```

A local smoke run of the handler itself (safe: `DRY_RUN` defaults to `true`, and
each service block catches its own boto3 error when no credentials are present):

```bash
cd infra/lambda/teardown
DRY_RUN=true python handler.py
```

The tests cover: the DRY_RUN path makes zero mutating calls; only
`Project=harbormaster` resources are selected; only the `eks_frontdoor` NLB is
selected; a simulated single-service outage does not abort the run; and the
wet-run path performs the actions and publishes to SNS.
