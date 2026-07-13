# Runbook: W4 EKS, KEDA, Flink backpressure, and teardown proof

W4 is one scheduled, Arun-run AWS window. Its purpose is to close the three
remaining Phase 5 live criteria with run artifacts:

1. KEDA serving scale from 0 to N and back to 0, including first successful
   signed inference latency.
2. A real Managed Flink backpressure episode with Kinesis lag and drain
   evidence.
3. The EventBridge Scheduler driven teardown guard deleting the EKS node group
   and cluster.

The local code and tests prepare this window. Arun pastes every command marked
`ARUN RUNS`. Codex may prepare files and perform read-only verification, but it
must not run an AWS, Terraform, ECR, S3, or Kubernetes mutation.

Account: `645322802947`. Region: `us-east-1`. The $75 monthly FinOps cap and
the nightly teardown Lambda remain active throughout the window.

Use the administrator identity only for Sections 2 and 3. After the IAM
reconciliation, assume `harbormaster-platform` and use that role for every
Terraform, AWS data-plane, ECR, S3, and Kubernetes action in Sections 4 onward.
The budget action attaches the spend freeze to that role.

## Current state and boundaries

- The IAM permissions boundary is applied at version v2. W4 adds
  `execute-api:Invoke` plus an exact platform-principal IAM ceiling, so Arun
  creates one new managed-policy version. Do not rerun
  `infra/aws/bootstrap.sh`.
- Phase 1 is live. No EKS cluster, MSK cluster, or SageMaker endpoint was live
  at the 2026-07-12 handoff.
- The local Debezium connector registration leg is fixed and proven locally.
  Its AWS retry is optional and is not part of W4.
- The API Gateway route uses `AWS_IAM`. Plain `curl` is not a valid health
  check. The observer and Flink job sign requests with SigV4.
- Terraform owns the internal NLB. A security-group chain admits only API
  Gateway VPC-link traffic to the NLB and only NLB traffic to the fixed
  NodePort on port 30080. Do not install an AWS load balancer controller.
- EKS is pinned to Kubernetes 1.34 with standard support only. KEDA is pinned
  to 2.20.0, whose tested compatibility window includes Kubernetes 1.34.
- W4 uses one worker. KEDA scales serving pods; it does not scale EKS nodes.
- NAT is enabled only for this bounded window so private workers and the Flink
  runtime can reach required public AWS endpoints. Disable it during cleanup.
- `phase5_guard_dry_run` and the nightly `teardown_dry_run` must both be
  `false` before EKS is created.
- The wet nightly sweep runs at 07:00 UTC and intentionally removes tagged
  Flink, EKS front-door NLB, NAT, and worker capacity. Schedule W4 to finish at
  least 30 minutes before that sweep, or start after it. Do not disable it.

Stop immediately if any preflight identity, budget, plan, or guard check is
unexpected. Never use `make destroy`.

## 1. Local preparation, no AWS mutation

Run from a clean, current `master` after the W4 readiness PR is merged.

```bash
set -euo pipefail
cd ~/code/harbormaster
git status --short
git pull --ff-only
make serve-install
make serve-test
make validate
make flink-package
```

The expected Flink artifact is `dist/flink-app.zip`. Confirm all five exact
runtime members are present:

```bash
for member in \
  main.py \
  requirements.txt \
  flink/__init__.py \
  flink/window_logic.py \
  lib/pyflink-dependencies.jar; do
  unzip -Z1 dist/flink-app.zip | rg -Fx "$member"
done
```

Create one durable artifact directory. The Python timestamp is portable on
macOS and Linux.

```bash
export STAMP=$(python3 -c 'from datetime import UTC, datetime; print(datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))')
export ARTIFACT_DIR="$PWD/artifacts/w4/$STAMP"
mkdir -p "$ARTIFACT_DIR"
printf '%s\n' "$ARTIFACT_DIR"
```

Do not pre-create `docs/drills/M3_backpressure_loadtest.md` with estimated
numbers. It is written after this window from the artifacts above.

## 2. Read-only AWS preflight

`ARUN RUNS`:

```bash
set -euo pipefail
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
test "$ACCOUNT_ID" = "645322802947"
aws sts get-caller-identity | tee "$ARTIFACT_DIR/caller-identity.json"
ADMIN_CALLER_ARN=$(jq -r .Arn "$ARTIFACT_DIR/caller-identity.json")
case "$ADMIN_CALLER_ARN" in
  "arn:aws:iam::${ACCOUNT_ID}:user/"*) ;;
  *) printf 'expected a direct IAM administrator, got: %s\n' \
       "$ADMIN_CALLER_ARN" >&2; exit 1 ;;
esac
export ADMIN_CALLER_ARN

aws budgets describe-budget \
  --account-id "$ACCOUNT_ID" \
  --budget-name harbormaster-base-hard-75 \
  | tee "$ARTIFACT_DIR/hard-budget.json"
aws budgets describe-budget-actions-for-budget \
  --account-id "$ACCOUNT_ID" \
  --budget-name harbormaster-base-hard-75 \
  | tee "$ARTIFACT_DIR/hard-budget-actions.json"
aws scheduler get-schedule --name harbormaster-base-nightly-teardown \
  | tee "$ARTIFACT_DIR/nightly-teardown-preflight.json"
TEARDOWN_LAMBDA_PREFIX="arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:"
TEARDOWN_LAMBDA_ARN=$(jq -er --arg prefix "$TEARDOWN_LAMBDA_PREFIX" \
  '.Target.Arn | select(startswith($prefix))' \
  "$ARTIFACT_DIR/nightly-teardown-preflight.json")
aws lambda get-function-configuration --function-name "$TEARDOWN_LAMBDA_ARN" \
  | tee "$ARTIFACT_DIR/nightly-teardown-lambda-preflight.json"

jq -e '
  .Budget.BudgetLimit.Unit == "USD" and
  (.Budget.BudgetLimit.Amount | tonumber) == 75 and
  (.Budget.CalculatedSpend.ActualSpend.Amount | tonumber) < 75
' "$ARTIFACT_DIR/hard-budget.json"
SPEND_FREEZE_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/harbormaster-base-spend-freeze"
jq -e --arg policy "$SPEND_FREEZE_ARN" --arg role harbormaster-platform '
  .Actions | any(.[];
    .ActionType == "APPLY_IAM_POLICY" and
    .ApprovalModel == "AUTOMATIC" and
    .Status == "STANDBY" and
    .Definition.IamActionDefinition.PolicyArn == $policy and
    (.Definition.IamActionDefinition.Roles | index($role)) != null
  )
' "$ARTIFACT_DIR/hard-budget-actions.json"
jq -e '
  .State == "ENABLED" and
  .ScheduleExpression == "cron(0 7 * * ? *)"
' "$ARTIFACT_DIR/nightly-teardown-preflight.json"
if jq -e '.Environment.Variables.DRY_RUN == "false"' \
  "$ARTIFACT_DIR/nightly-teardown-lambda-preflight.json"; then
  NIGHTLY_TEARDOWN_WET=true
else
  NIGHTLY_TEARDOWN_WET=false
fi
export NIGHTLY_TEARDOWN_WET

BOUNDARY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/harbormaster-permissions-boundary"
aws iam get-policy --policy-arn "$BOUNDARY_ARN" \
  | tee "$ARTIFACT_DIR/boundary-before.json"

aws eks list-clusters | tee "$ARTIFACT_DIR/eks-before.json"
aws kafka list-clusters-v2 | tee "$ARTIFACT_DIR/msk-before.json"
aws sagemaker list-endpoints | tee "$ARTIFACT_DIR/sagemaker-before.json"
jq -e '.Policy.DefaultVersionId == "v2"' "$ARTIFACT_DIR/boundary-before.json"
jq -e '.clusters | all(. != "harbormaster-base-eks")' \
  "$ARTIFACT_DIR/eks-before.json"
```

Required preflight verdicts:

- Caller account is exactly `645322802947`.
- The hard budget limit is 75 USD, current spend is below it, and at least one
  automatic IAM freeze action is armed in `STANDBY` for the exact
  `harbormaster-base-spend-freeze` policy and `harbormaster-platform` role.
- The boundary exists and reports v2 as its current default.
- No Harbormaster EKS cluster exists.
- The nightly teardown schedule is enabled at 07:00 UTC. Its Lambda reports
  `DRY_RUN=false`, or the guard-only Stage 0 apply below must complete before
  any EKS plan is generated. This window must not overlap that sweep.

The internal NLB needs the Elastic Load Balancing service-linked role. Check it
without changing anything:

```bash
aws iam get-role --role-name AWSServiceRoleForElasticLoadBalancing \
  | tee "$ARTIFACT_DIR/elb-service-linked-role.json"
```

If that returns `NoSuchEntity`, this one bootstrap action is required.
`ARUN RUNS`:

```bash
aws iam create-service-linked-role \
  --aws-service-name elasticloadbalancing.amazonaws.com
```

## 3. Update the existing permissions boundary

The Flink service role now has a resource-scoped `execute-api:Invoke` identity
policy. The platform role also needs tightly scoped IAM lifecycle actions for
EKS, KEDA, and their service-linked roles. The already-applied boundary must
permit both sets because effective permissions are the intersection of the
identity policy and boundary.

First inspect the exact committed actions and the budget-action exception:

```bash
rg -n 'execute-api:Invoke' infra/aws/harbormaster-permissions-boundary.json
jq '.Statement[] | select(
  .Sid == "PlatformManageBoundedRoles" or
  .Sid == "AllowBudgetActionSpendFreeze" or
  .Sid == "DenyPlatformSelfMutation" or
  .Sid == "DenyBoundaryPolicyMutation" or
  .Sid == "DenyAllIamWriteEscalation"
)' \
  infra/aws/harbormaster-permissions-boundary.json
jq '.Statement[] | select(.Sid == "PassOnlyHarbormasterRolesToServices" or .Sid == "ManageHarbormasterEksOidcProvider" or .Sid == "CreateHarbormasterServiceLinkedRoles")' \
  infra/aws/harbormaster-platform-permissions.json
```

`ARUN RUNS`:

```bash
NEW_BOUNDARY_VERSION=$(aws iam create-policy-version \
  --policy-arn "$BOUNDARY_ARN" \
  --policy-document file://infra/aws/harbormaster-permissions-boundary.json \
  --set-as-default \
  --query 'PolicyVersion.VersionId' \
  --output text)

aws iam get-policy-version \
  --policy-arn "$BOUNDARY_ARN" \
  --version-id "$NEW_BOUNDARY_VERSION" \
  | tee "$ARTIFACT_DIR/boundary-after.json"

aws iam get-role --role-name harbormaster-base-budget-action \
  | tee "$ARTIFACT_DIR/budget-action-role.json"
aws iam get-role-policy \
  --role-name harbormaster-base-budget-action \
  --policy-name harbormaster-base-budget-action-exec \
  | tee "$ARTIFACT_DIR/budget-action-role-policy.json"

jq -e --arg boundary "$BOUNDARY_ARN" \
  '.Role.PermissionsBoundary.PermissionsBoundaryArn == $boundary' \
  "$ARTIFACT_DIR/budget-action-role.json"
jq -e --arg policy "$SPEND_FREEZE_ARN" \
  --arg target "arn:aws:iam::${ACCOUNT_ID}:role/harbormaster-platform" '
  .PolicyDocument.Statement | any(.[];
    .Effect == "Allow" and
    (([.Action] | flatten) | index("iam:AttachRolePolicy")) != null and
    (([.Action] | flatten) | index("iam:DetachRolePolicy")) != null and
    (([.Resource] | flatten) | index($target)) != null and
    .Condition.ArnEquals["iam:PolicyARN"] == $policy
  )
' "$ARTIFACT_DIR/budget-action-role-policy.json"

BUDGET_ACTION_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/harbormaster-base-budget-action"
aws iam simulate-principal-policy \
  --policy-source-arn "$BUDGET_ACTION_ROLE_ARN" \
  --action-names iam:AttachRolePolicy \
  --resource-arns "arn:aws:iam::${ACCOUNT_ID}:role/harbormaster-platform" \
  --context-entries \
    "ContextKeyName=aws:PrincipalArn,ContextKeyValues=$BUDGET_ACTION_ROLE_ARN,ContextKeyType=string" \
    "ContextKeyName=iam:PolicyARN,ContextKeyValues=$SPEND_FREEZE_ARN,ContextKeyType=string" \
  | tee "$ARTIFACT_DIR/budget-action-effective-policy.json"
jq -e '
  .EvaluationResults | any(.[];
    .EvalActionName == "iam:AttachRolePolicy" and
    .EvalDecision == "allowed"
  )
' "$ARTIFACT_DIR/budget-action-effective-policy.json"
```

Stop unless the returned policy document contains `execute-api:Invoke` and the
tightly conditioned `AllowBudgetActionSpendFreeze` statement. Its principal
must be the base or demo budget-action role, its target must be
`harbormaster-platform`, and its policy must be the matching spend-freeze
policy. Do not delete v2 during this window. It is the immediate rollback
policy version.

Reconcile the already-existing platform role's inline policy so its deferred
least-privilege path can create EKS roles, service-linked roles, and the
cluster-scoped OIDC provider. This does not switch the active identity.

```bash
aws iam get-role-policy \
  --role-name harbormaster-platform \
  --policy-name harbormaster-iam-management \
  | tee "$ARTIFACT_DIR/platform-policy-before.json"
```

`ARUN RUNS`:

```bash
aws iam put-role-policy \
  --role-name harbormaster-platform \
  --policy-name harbormaster-iam-management \
  --policy-document file://infra/aws/harbormaster-platform-permissions.json

aws iam update-role \
  --role-name harbormaster-platform \
  --max-session-duration 28800
```

Read-only verification:

```bash
aws iam get-role-policy \
  --role-name harbormaster-platform \
  --policy-name harbormaster-iam-management \
  | tee "$ARTIFACT_DIR/platform-policy-after.json"
```

Use the read-only IAM simulator against the deployed role and its new default
boundary version. These calls do not execute the requested IAM actions. They
must prove both the required path and the boundary's negative controls before
the role is assumed.

```bash
PLATFORM_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/harbormaster-platform"
PLATFORM_PRINCIPAL_CONTEXT="ContextKeyName=aws:PrincipalArn,ContextKeyValues=$PLATFORM_ROLE_ARN,ContextKeyType=string"

simulate_platform() {
  local label="$1"
  local expected="$2"
  shift 2
  local output="$ARTIFACT_DIR/platform-simulation-$label.json"
  aws iam simulate-principal-policy \
    --policy-source-arn "$PLATFORM_ROLE_ARN" \
    "$@" \
    | tee "$output"
  jq -e --arg expected "$expected" '
    .EvaluationResults as $results |
    ($results | length) > 0 and
    ($results | all(.EvalDecision == $expected))
  ' "$output"
}

SIMULATED_ROLE="arn:aws:iam::${ACCOUNT_ID}:role/harbormaster-base-w4-simulated"
simulate_platform bounded-role allowed \
  --action-names iam:CreateRole iam:PutRolePolicy iam:AttachRolePolicy iam:TagRole \
  --resource-arns "$SIMULATED_ROLE" \
  --context-entries \
    "$PLATFORM_PRINCIPAL_CONTEXT" \
    "ContextKeyName=iam:PermissionsBoundary,ContextKeyValues=$BOUNDARY_ARN,ContextKeyType=string"

simulate_platform pass-role allowed \
  --action-names iam:PassRole \
  --resource-arns "$SIMULATED_ROLE" \
  --context-entries \
    "$PLATFORM_PRINCIPAL_CONTEXT" \
    "ContextKeyName=iam:PassedToService,ContextKeyValues=eks.amazonaws.com,ContextKeyType=string"

simulate_platform eks-oidc allowed \
  --action-names iam:CreateOpenIDConnectProvider \
  --resource-arns \
    "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/SIMULATED" \
  --context-entries "$PLATFORM_PRINCIPAL_CONTEXT"

simulate_platform instance-profile allowed \
  --action-names iam:CreateInstanceProfile \
  --resource-arns \
    "arn:aws:iam::${ACCOUNT_ID}:instance-profile/harbormaster-base-w4-simulated" \
  --context-entries "$PLATFORM_PRINCIPAL_CONTEXT"

simulate_platform service-linked-role allowed \
  --action-names iam:CreateServiceLinkedRole \
  --resource-arns \
    "arn:aws:iam::${ACCOUNT_ID}:role/aws-service-role/eks.amazonaws.com/AWSServiceRoleForAmazonEKS" \
  --context-entries \
    "$PLATFORM_PRINCIPAL_CONTEXT" \
    "ContextKeyName=iam:AWSServiceName,ContextKeyValues=eks.amazonaws.com,ContextKeyType=string"

simulate_platform self-mutation explicitDeny \
  --action-names iam:PutRolePolicy \
  --resource-arns "$PLATFORM_ROLE_ARN" \
  --context-entries \
    "$PLATFORM_PRINCIPAL_CONTEXT" \
    "ContextKeyName=iam:PermissionsBoundary,ContextKeyValues=$BOUNDARY_ARN,ContextKeyType=string"

simulate_platform unrelated-role implicitDeny \
  --action-names iam:CreateRole \
  --resource-arns "arn:aws:iam::${ACCOUNT_ID}:role/unrelated-w4-simulated" \
  --context-entries \
    "$PLATFORM_PRINCIPAL_CONTEXT" \
    "ContextKeyName=iam:PermissionsBoundary,ContextKeyValues=$BOUNDARY_ARN,ContextKeyType=string"

simulate_platform boundary-mutation explicitDeny \
  --action-names iam:CreatePolicyVersion \
  --resource-arns "$BOUNDARY_ARN" \
  --context-entries "$PLATFORM_PRINCIPAL_CONTEXT"
```

Stop unless every assertion matches its named decision. The simulator is a
read-only authorization check; the saved policy documents and these results
remain the evidence for the exact role and boundary used in W4.

Now assume the bounded deployment identity. Replace the MFA device ARN, then
enter a fresh six-digit code. If the current administrator session is itself an
assumed role, AWS role chaining limits this session to one hour; use a direct
MFA-backed administrator identity for the eight-hour window.

`ARUN RUNS`:

```bash
export MFA_SERIAL="arn:aws:iam::${ACCOUNT_ID}:mfa/REPLACE_WITH_DEVICE_NAME"
MFA_TOKEN=$(python3 -c 'import getpass; print(getpass.getpass("MFA code: "))')

PLATFORM_SESSION=$(aws sts assume-role \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/harbormaster-platform" \
  --role-session-name w4 \
  --serial-number "$MFA_SERIAL" \
  --token-code "$MFA_TOKEN" \
  --duration-seconds 28800)

AWS_ACCESS_KEY_ID=$(jq -r '.Credentials.AccessKeyId' <<<"$PLATFORM_SESSION")
AWS_SECRET_ACCESS_KEY=$(jq -r '.Credentials.SecretAccessKey' <<<"$PLATFORM_SESSION")
AWS_SESSION_TOKEN=$(jq -r '.Credentials.SessionToken' <<<"$PLATFORM_SESSION")
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
unset MFA_TOKEN PLATFORM_SESSION

PLATFORM_CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
case "$PLATFORM_CALLER_ARN" in
  "arn:aws:sts::${ACCOUNT_ID}:assumed-role/harbormaster-platform/"*) ;;
  *) printf 'unexpected caller: %s\n' "$PLATFORM_CALLER_ARN" >&2; exit 1 ;;
esac
aws sts get-caller-identity | tee "$ARTIFACT_DIR/platform-caller-identity.json"
```

Run every remaining command in this same shell. If the session expires,
restore and verify the original direct administrator before repeating the
assume-role block with a fresh MFA code:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
RESTORED_CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
test "$RESTORED_CALLER_ARN" = "$ADMIN_CALLER_ARN"
```

Then repeat the MFA prompt and `aws sts assume-role` block above, export the
three fresh session values, and re-run the `PLATFORM_CALLER_ARN` assertion
before continuing.

## 4. Create EKS only after both teardown guards are wet

### Stage 0: remediate a dry nightly teardown before the EKS plan

If `NIGHTLY_TEARDOWN_WET=false`, change only these values in the gitignored
`infra/terraform/envs/base/terraform.tfvars`, preserving all other live Phase 1
values:

```hcl
enable_phase1           = true
enable_nightly_teardown = true
teardown_dry_run        = false
enable_phase5           = false
```

The separate saved plan may update the existing nightly teardown Lambda and
its FinOps IAM resources. It must contain no Phase 5 resource address. Arun
runs the mutation only when the read-only preflight found the Lambda dry.

`ARUN RUNS`:

```bash
if test "$NIGHTLY_TEARDOWN_WET" = false; then
  PLAN_LABEL=wave4-w4-nightly-guard
  PLAN_FILE="$ARTIFACT_DIR/$PLAN_LABEL.tfplan"
  PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$PLAN_LABEL.json"
  scripts/plan_artifact.sh "$PLAN_LABEL" "$PLAN_FILE"
  terraform -chdir=infra/terraform/envs/base show -no-color "$PLAN_FILE" \
    | tee "$ARTIFACT_DIR/$PLAN_LABEL.plan.txt"
  test "$(shasum -a 256 "$PLAN_FILE" | awk '{print $1}')" = \
    "$(jq -r .plan_sha256 "$PLAN_SUMMARY")"
  jq -e '
    all(.resource_changes[]?;
      if .actions == ["no-op"] then true
      else
        (.address | startswith("module.finops.")) and
        ((.actions | index("delete")) == null)
      end
    )
  ' "$PLAN_SUMMARY"
  make apply-plan PLAN="$PLAN_FILE"
fi

aws lambda get-function-configuration --function-name "$TEARDOWN_LAMBDA_ARN" \
  | tee "$ARTIFACT_DIR/nightly-teardown-lambda-before-eks.json"
jq -e '.Environment.Variables.DRY_RUN == "false"' \
  "$ARTIFACT_DIR/nightly-teardown-lambda-before-eks.json"
```

The final `jq` assertion is mandatory even when Stage 0 was skipped. Stop
before the EKS plan if it fails.

### Stage 1: create EKS, one worker, NLB, and the armed guard

Set these values in the gitignored
`infra/terraform/envs/base/terraform.tfvars`:

```hcl
enable_phase1          = true
enable_nat             = true
enable_nightly_teardown = true
teardown_dry_run       = false

enable_phase5                   = true
enable_phase5_kubernetes_access = false
enable_phase5_keda              = false
phase5_endpoint_public_access   = true
phase5_public_access_cidrs      = ["REPLACE_WITH_OPERATOR_PUBLIC_IP/32"]
phase5_node_desired_size        = 1
phase5_guard_dry_run            = false
phase5_teardown_max_age_hours   = 4
phase5_teardown_schedule_expression = "rate(30 minutes)"
phase5_keep_alive_until         = ""

serving_target = "ecs"
```

Discover the operator address, then insert only that `/32` in tfvars:

```bash
OPERATOR_IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')
printf '%s/32\n' "$OPERATOR_IP"
```

`ARUN RUNS`:

```bash
PLAN_LABEL=wave4-w4-eks
PLAN_FILE="$ARTIFACT_DIR/$PLAN_LABEL.tfplan"
PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$PLAN_LABEL.json"
scripts/plan_artifact.sh "$PLAN_LABEL" "$PLAN_FILE"
terraform -chdir=infra/terraform/envs/base show -no-color "$PLAN_FILE" \
  | tee "$ARTIFACT_DIR/$PLAN_LABEL.plan.txt"
test "$(shasum -a 256 "$PLAN_FILE" | awk '{print $1}')" = \
  "$(jq -r .plan_sha256 "$PLAN_SUMMARY")"
```

Review the plan before approval. It may add the EKS cluster, one managed node
group, EKS and KEDA IAM/OIDC resources, internal NLB and target group, guard
Lambda and Scheduler, and NAT. It also updates the existing spend-freeze
policy plus the nightly teardown Lambda and role so tagged NLB, NAT, and
Elastic IP costs are covered. It must not delete or replace Phase 1 data
stores. It must leave the API Gateway route on ECS.

`ARUN RUNS`:

```bash
make apply-plan PLAN="$PLAN_FILE"
```

Read-only verification:

```bash
CLUSTER=$(terraform -chdir=infra/terraform/envs/base output -raw phase5_cluster_name)
NODE_GROUP=$(terraform -chdir=infra/terraform/envs/base output -raw phase5_node_group_name)
GUARD=$(terraform -chdir=infra/terraform/envs/base output -raw phase5_teardown_guard_function_name)
SCHEDULE=$(terraform -chdir=infra/terraform/envs/base output -raw phase5_teardown_guard_schedule_name)

aws eks describe-cluster --name "$CLUSTER" \
  | tee "$ARTIFACT_DIR/eks-created.json"
aws eks describe-nodegroup --cluster-name "$CLUSTER" --nodegroup-name "$NODE_GROUP" \
  | tee "$ARTIFACT_DIR/nodegroup-created.json"
aws scheduler get-schedule --name "$SCHEDULE" \
  | tee "$ARTIFACT_DIR/guard-schedule.json"
aws lambda get-function-configuration --function-name "$GUARD" \
  | tee "$ARTIFACT_DIR/guard-function.json"
aws iam get-role --role-name harbormaster-base-budget-action \
  | tee "$ARTIFACT_DIR/budget-action-role-after-stage1.json"

jq -e '
  .cluster.status == "ACTIVE" and
  .cluster.version == "1.34" and
  .cluster.upgradePolicy.supportType == "STANDARD"
' "$ARTIFACT_DIR/eks-created.json"
jq -e '
  .nodegroup.status == "ACTIVE" and
  .nodegroup.scalingConfig.desiredSize == 1
' "$ARTIFACT_DIR/nodegroup-created.json"
jq -e '.State == "ENABLED"' "$ARTIFACT_DIR/guard-schedule.json"
jq -e '
  .Environment.Variables.DRY_RUN == "false" and
  .Environment.Variables.MAX_AGE_HOURS == "4"
' "$ARTIFACT_DIR/guard-function.json"
jq -e --arg account "$ACCOUNT_ID" '
  .Role.AssumeRolePolicyDocument.Statement | any(.[];
    .Principal.Service == "budgets.amazonaws.com" and
    .Condition.StringEquals["aws:SourceAccount"] == $account and
    .Condition.ArnLike["aws:SourceArn"] ==
      ("arn:aws:budgets::" + $account + ":budget/harbormaster-base-hard-75")
  )
' "$ARTIFACT_DIR/budget-action-role-after-stage1.json"
```

Stop unless the cluster and node group are `ACTIVE`, desired worker count is
1, the cluster version is `1.34`, upgrade support type is `STANDARD`, the
schedule is enabled, `DRY_RUN` is `false`, and `MAX_AGE_HOURS` is `4`.

## 5. Stage 2: enable Terraform Kubernetes access and install KEDA

Change only:

```hcl
enable_phase5_kubernetes_access = true
enable_phase5_keda              = true
```

`ARUN RUNS`:

```bash
PLAN_LABEL=wave4-w4-keda
PLAN_FILE="$ARTIFACT_DIR/$PLAN_LABEL.tfplan"
PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$PLAN_LABEL.json"
scripts/plan_artifact.sh "$PLAN_LABEL" "$PLAN_FILE"
terraform -chdir=infra/terraform/envs/base show -no-color "$PLAN_FILE" \
  | tee "$ARTIFACT_DIR/$PLAN_LABEL.plan.txt"
test "$(shasum -a 256 "$PLAN_FILE" | awk '{print $1}')" = \
  "$(jq -r .plan_sha256 "$PLAN_SUMMARY")"
make apply-plan PLAN="$PLAN_FILE"
aws eks update-kubeconfig --name "$CLUSTER" --region "$AWS_REGION"
```

Read-only verification:

```bash
kubectl get nodes -o wide | tee "$ARTIFACT_DIR/k8s-nodes.txt"
kubectl get pods -n keda -o wide | tee "$ARTIFACT_DIR/keda-pods.txt"
kubectl get serviceaccount -n keda keda-operator -o yaml \
  | tee "$ARTIFACT_DIR/keda-service-account.yaml"
```

All KEDA pods must be running. The operator service account must carry the
Terraform-created IRSA role. Stop if the operator logs show credential or
CloudWatch authorization errors.

## 6. Build, push, resolve, and render an immutable serving image

The ECR push and Kubernetes apply are live mutations, so Arun runs them. Use a
commit tag for traceability, then deploy only the resolved digest.

`ARUN RUNS`:

```bash
GIT_SHA=$(git rev-parse --short=12 HEAD)
SERVING_REPO=$(terraform -chdir=infra/terraform/envs/base output -raw serving_ecr_repository_url)
REGISTRY="${SERVING_REPO%%/*}"

aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"
docker buildx build \
  --platform linux/amd64 \
  -f serving/Dockerfile \
  -t "$SERVING_REPO:w4-$GIT_SHA" \
  --push .

IMAGE_DIGEST=$(aws ecr describe-images \
  --repository-name "${SERVING_REPO#*/}" \
  --image-ids imageTag="w4-$GIT_SHA" \
  --query 'imageDetails[0].imageDigest' \
  --output text)
IMAGE="$SERVING_REPO@$IMAGE_DIGEST"

RENDERED_MANIFEST="$ARTIFACT_DIR/serving-$GIT_SHA.yaml"
make phase5-render-serving \
  IMAGE="$IMAGE" \
  REPOSITORY="$SERVING_REPO" \
  OUTPUT="$RENDERED_MANIFEST"
rg -n 'image:|nodePort:|kind: ScaledObject' "$RENDERED_MANIFEST"
kubectl apply -f "$RENDERED_MANIFEST"
```

Read-only verification before load:

```bash
kubectl -n hm-serving get deployment,service,scaledobject,hpa -o wide \
  | tee "$ARTIFACT_DIR/serving-before-load.txt"
kubectl -n hm-serving get deployment serving \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

The deployed image must equal `$IMAGE`, the Service must use NodePort 30080,
and desired and available replicas must both be 0 before measurement begins.

## 7. Package and start the signed Managed Flink job

Use a unique S3 key so Terraform observes a code revision. The module reads the
artifact from the lake bucket.

`ARUN RUNS`:

```bash
LAKE_BUCKET=$(terraform -chdir=infra/terraform/envs/base output -raw lake_bucket_name)
FLINK_KEY="flink/w4-$GIT_SHA/flink-app.zip"
aws s3 cp dist/flink-app.zip "s3://$LAKE_BUCKET/$FLINK_KEY"
```

Set the exact key in tfvars:

```hcl
flink_code_s3_key = "flink/w4-REPLACE_WITH_GIT_SHA/flink-app.zip"
```

`ARUN RUNS`:

```bash
PLAN_LABEL=wave4-w4-flink
PLAN_FILE="$ARTIFACT_DIR/$PLAN_LABEL.tfplan"
PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$PLAN_LABEL.json"
scripts/plan_artifact.sh "$PLAN_LABEL" "$PLAN_FILE"
terraform -chdir=infra/terraform/envs/base show -no-color "$PLAN_FILE" \
  | tee "$ARTIFACT_DIR/$PLAN_LABEL.plan.txt"
test "$(shasum -a 256 "$PLAN_FILE" | awk '{print $1}')" = \
  "$(jq -r .plan_sha256 "$PLAN_SUMMARY")"
make apply-plan PLAN="$PLAN_FILE"

FLINK_APP=$(terraform -chdir=infra/terraform/envs/base output -raw flink_application_name)
aws kinesisanalyticsv2 start-application --application-name "$FLINK_APP"
```

Wait with read-only calls until the application reports `RUNNING`:

```bash
while true; do
  STATUS=$(aws kinesisanalyticsv2 describe-application \
    --application-name "$FLINK_APP" \
    --query 'ApplicationDetail.ApplicationStatus' \
    --output text)
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$STATUS"
  if test "$STATUS" = RUNNING; then
    FLINK_RUNNING_EPOCH=$(date +%s)
    break
  fi
  test "$STATUS" = READY && sleep 15 && continue
  test "$STATUS" = STARTING && sleep 15 && continue
  exit 1
done
```

Save the application description and its available CloudWatch metric
dimensions:

```bash
aws kinesisanalyticsv2 describe-application --application-name "$FLINK_APP" \
  | tee "$ARTIFACT_DIR/flink-running.json"
aws cloudwatch list-metrics --namespace AWS/KinesisAnalytics \
  --dimensions Name=Application,Value="$FLINK_APP" \
  | tee "$ARTIFACT_DIR/flink-metrics.json"
```

Before retargeting traffic, wait for the CloudWatch scaler to observe the
running Flink consumer and settle back to zero. This prevents healthy iterator
age jitter, or a startup backlog still inside the 300-second metric window,
from consuming the required zero-replica baseline. The 5-second activation
threshold remains below the deliberate 30-second backlog target.

```bash
KEDA_STABLE_SAMPLES=0
: > "$ARTIFACT_DIR/keda-flink-stabilization.jsonl"
for attempt in $(seq 1 40); do
  SCALED_OBJECT=$(kubectl -n hm-serving get scaledobject serving-scaler -o json)
  DEPLOYMENT=$(kubectl -n hm-serving get deployment serving -o json)
  KEDA_READY=$(jq -r \
    '[.status.conditions[]? | select(.type == "Ready")][0].status // "Unknown"' \
    <<< "$SCALED_OBJECT")
  KEDA_ACTIVE=$(jq -r \
    '[.status.conditions[]? | select(.type == "Active")][0].status // "Unknown"' \
    <<< "$SCALED_OBJECT")
  DESIRED_REPLICAS=$(jq -r '.spec.replicas // 0' <<< "$DEPLOYMENT")
  AVAILABLE_REPLICAS=$(jq -r '.status.availableReplicas // 0' <<< "$DEPLOYMENT")
  SECONDS_SINCE_FLINK_RUNNING=$(($(date +%s) - FLINK_RUNNING_EPOCH))

  jq -nc \
    --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson attempt "$attempt" \
    --arg ready "$KEDA_READY" \
    --arg active "$KEDA_ACTIVE" \
    --argjson desired "$DESIRED_REPLICAS" \
    --argjson available "$AVAILABLE_REPLICAS" \
    --argjson seconds_since_flink_running "$SECONDS_SINCE_FLINK_RUNNING" \
    '{at: $at, attempt: $attempt, ready: $ready, active: $active,
      desired_replicas: $desired, available_replicas: $available,
      seconds_since_flink_running: $seconds_since_flink_running}' \
    | tee -a "$ARTIFACT_DIR/keda-flink-stabilization.jsonl"

  if test "$SECONDS_SINCE_FLINK_RUNNING" -ge 300 && \
     test "$KEDA_READY" = True && test "$KEDA_ACTIVE" = False && \
     test "$DESIRED_REPLICAS" -eq 0 && test "$AVAILABLE_REPLICAS" -eq 0; then
    KEDA_STABLE_SAMPLES=$((KEDA_STABLE_SAMPLES + 1))
  else
    KEDA_STABLE_SAMPLES=0
  fi
  test "$KEDA_STABLE_SAMPLES" -ge 2 && break
  sleep 30
done
test "$KEDA_STABLE_SAMPLES" -ge 2
```

Stop if stabilization does not complete. Do not retarget API Gateway or start
the measurement with a nonzero Deployment.

## 8. Retarget API Gateway from ECS to EKS

Change only:

```hcl
serving_target = "eks"
```

`ARUN RUNS`:

```bash
PLAN_LABEL=wave4-w4-retarget-eks
PLAN_FILE="$ARTIFACT_DIR/$PLAN_LABEL.tfplan"
PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$PLAN_LABEL.json"
scripts/plan_artifact.sh "$PLAN_LABEL" "$PLAN_FILE"
terraform -chdir=infra/terraform/envs/base show -no-color "$PLAN_FILE" \
  | tee "$ARTIFACT_DIR/$PLAN_LABEL.plan.txt"
test "$(shasum -a 256 "$PLAN_FILE" | awk '{print $1}')" = \
  "$(jq -r .plan_sha256 "$PLAN_SUMMARY")"
make apply-plan PLAN="$PLAN_FILE"
```

The plan must update the API Gateway route only. ECS remains the rollback
backend. At zero serving replicas, an EKS-path health request may return a
non-200 response until KEDA sees lag and scales out.

## 9. Measure scale and backpressure with artifacts

Run the observer and load generator from the same shell so they share the
artifact directory and command status. The observer starts first, persists its
baseline, waits for the load generator's running artifact, reads only
Deployment state, sends SigV4 inference requests, and records the 0 to N to 0
timeline. Inference latency is a sampled upper bound because requests are sent
at the observer's polling interval.

`ARUN RUNS`:

```bash
SERVING_API=$(terraform -chdir=infra/terraform/envs/base output -raw serving_api_endpoint)
KINESIS_STREAM_NAME=$(terraform -chdir=infra/terraform/envs/base output -raw kinesis_stream_name)
W4_RUN_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
LOAD_ARTIFACT="$ARTIFACT_DIR/kinesis-load.json"
SCALE_ARTIFACT="$ARTIFACT_DIR/scale-timeline.json"
BACKPRESSURE_ARTIFACT="$ARTIFACT_DIR/flink-backpressure.json"
test ! -e "$LOAD_ARTIFACT"
test ! -e "$SCALE_ARTIFACT"
test ! -e "$BACKPRESSURE_ARTIFACT"

FLINK_DASHBOARD_URL=$(aws kinesisanalyticsv2 create-application-presigned-url \
  --application-name "$FLINK_APP" \
  --url-type FLINK_DASHBOARD_URL \
  --session-expiration-duration-in-seconds 3600 \
  --query AuthorizedUrl \
  --output text)
test -n "$FLINK_DASHBOARD_URL"
test "$FLINK_DASHBOARD_URL" != None

.venv/bin/python scripts/observe_phase5_scale.py \
  --api-url "$SERVING_API" \
  --load-artifact "$LOAD_ARTIFACT" \
  --output "$SCALE_ARTIFACT" \
  --run-id "$W4_RUN_ID" \
  --timeout-seconds 1800 &
OBSERVER_PID=$!

FLINK_DASHBOARD_URL="$FLINK_DASHBOARD_URL" \
W4_FLINK_BACKPRESSURE_ARTIFACT_PATH="$BACKPRESSURE_ARTIFACT" \
.venv/bin/python scripts/capture_flink_backpressure.py \
  --load-artifact "$LOAD_ARTIFACT" \
  --expected-run-id "$W4_RUN_ID" \
  --poll-interval-seconds 2 &
FLINK_CAPTURE_PID=$!

if W4_ARTIFACT_PATH="$LOAD_ARTIFACT" \
W4_OBSERVER_READY_PATH="$SCALE_ARTIFACT" \
W4_RUN_ID="$W4_RUN_ID" \
KINESIS_STREAM_NAME="$KINESIS_STREAM_NAME" \
STEADY_RPS=5 \
BURST_RPS=400 \
BURST_START_S=180 \
BURST_END_S=195 \
RAMP_S=0 \
DURATION_S=600 \
AWS_REGION="$AWS_REGION" \
.venv/bin/python scripts/loadtest_kinesis_backpressure.py; then
  LOAD_STATUS=0
else
  LOAD_STATUS=$?
  kill -TERM "$OBSERVER_PID" "$FLINK_CAPTURE_PID" 2>/dev/null || true
fi

if wait "$FLINK_CAPTURE_PID"; then
  FLINK_CAPTURE_STATUS=0
else
  FLINK_CAPTURE_STATUS=$?
fi
unset FLINK_DASHBOARD_URL

if wait "$OBSERVER_PID"; then
  OBSERVER_STATUS=0
else
  OBSERVER_STATUS=$?
fi

jq -n \
  --argjson load "$LOAD_STATUS" \
  --argjson observer "$OBSERVER_STATUS" \
  --argjson flink_capture "$FLINK_CAPTURE_STATUS" \
  '{load_exit: $load, observer_exit: $observer, flink_capture_exit: $flink_capture}' \
  | tee "$ARTIFACT_DIR/measurement-command-status.json"
```

The 180-second pre-burst interval allows the zero-replica cold start to
stabilize before the deliberate burst. Cold-start backpressure remains in the
raw samples. The pre-burst criterion uses only the final three pre-burst
samples, so it measures a recovered baseline rather than pretending the cold
start was idle. The 15-second high burst adds 5,925 records above the 5 rps
baseline and leaves 405 seconds for observed recovery. This is a bounded test
hypothesis, not a throughput claim; the recorded result decides criterion (b).

Optional read-only watches in a third terminal:

```bash
kubectl -n hm-serving get deployment,pods,hpa,scaledobject -w
```

After all three commands finish:

```bash
for artifact in "$LOAD_ARTIFACT" "$SCALE_ARTIFACT" "$BACKPRESSURE_ARTIFACT"; do
  if test -f "$artifact"; then
    jq . "$artifact"
  else
    printf 'missing evidence artifact: %s\n' "$artifact" >&2
  fi
done

if jq -e --arg run_id "$W4_RUN_ID" \
  '.status == "completed" and .run_id == $run_id' "$LOAD_ARTIFACT" && \
  jq -e --arg run_id "$W4_RUN_ID" \
  '.status == "completed" and .run_id == $run_id' "$SCALE_ARTIFACT" && \
  jq -e --arg run_id "$W4_RUN_ID" \
  '.status == "completed" and .run_id == $run_id' "$BACKPRESSURE_ARTIFACT"; then
  MEASUREMENT_ARTIFACTS_COMPLETE=true
else
  MEASUREMENT_ARTIFACTS_COMPLETE=false
fi

if jq -e '.summary.evaluated_conditions.all_conditions_true == true' \
  "$BACKPRESSURE_ARTIFACT"; then
  FLINK_BACKPRESSURE_CONDITIONS=true
else
  FLINK_BACKPRESSURE_CONDITIONS=false
fi

jq -n \
  --argjson artifacts_complete "$MEASUREMENT_ARTIFACTS_COMPLETE" \
  --argjson backpressure_conditions "$FLINK_BACKPRESSURE_CONDITIONS" \
  '{artifacts_complete: $artifacts_complete,
    backpressure_conditions: $backpressure_conditions}' \
  | tee "$ARTIFACT_DIR/measurement-evidence-verdict.json"
```

All three artifacts must report `status: completed` with the same fresh W4 run
ID. The timeline must contain
`scale_requested`, `pod_ready`, `first_inference_success`, and
`returned_to_zero`. The observer first persists a zero-replica, non-serving
EKS baseline; the load tool refuses to start until that marker exists. These
timestamps, not a stopwatch estimate, are the criterion (a) evidence.

Capture the matching CloudWatch window. `START_TIME` comes from the load
artifact. `END_TIME` comes from the observer's `returned_to_zero` event so the
query includes the post-load drain rather than stopping when writes stop.

```bash
KINESIS_METRIC_CAPTURED=false
FLINK_LAG_CAPTURED=false
if test "$MEASUREMENT_ARTIFACTS_COMPLETE" = true; then
  START_TIME=$(jq -r .started_at "$LOAD_ARTIFACT")
  END_TIME=$(jq -r .events.returned_to_zero.at "$SCALE_ARTIFACT")
  if test "$END_TIME" != "null" && test -n "$END_TIME"; then
    if aws cloudwatch get-metric-statistics \
      --namespace AWS/Kinesis \
      --metric-name GetRecords.IteratorAgeMilliseconds \
      --dimensions Name=StreamName,Value="$KINESIS_STREAM_NAME" \
      --start-time "$START_TIME" \
      --end-time "$END_TIME" \
      --period 60 \
      --statistics Maximum Average \
      | tee "$ARTIFACT_DIR/kinesis-iterator-age.json"; then
      KINESIS_METRIC_CAPTURED=true
    fi

    if aws cloudwatch get-metric-statistics \
      --namespace AWS/KinesisAnalytics \
      --metric-name millisBehindLatest \
      --dimensions Name=Application,Value="$FLINK_APP" \
      --start-time "$START_TIME" \
      --end-time "$END_TIME" \
      --period 60 \
      --statistics Maximum Average \
      | tee "$ARTIFACT_DIR/flink-lag.json"; then
      FLINK_LAG_CAPTURED=true
    fi
  fi
fi

jq -n \
  --argjson kinesis "$KINESIS_METRIC_CAPTURED" \
  --argjson flink_lag "$FLINK_LAG_CAPTURED" \
  '{kinesis_metric_captured: $kinesis, flink_lag_captured: $flink_lag}' \
  | tee "$ARTIFACT_DIR/measurement-metric-status.json"

```

Use the exact dimensions shown in `flink-metrics.json` if the live application
reports additional dimensions. Flink 1.20 does not publish
`backPressuredTimeMsPerSecond` through the Managed Flink CloudWatch namespace,
so the bound dashboard artifact is the backpressure source of truth. Criterion
(b) closes only if `all_conditions_true` is true: the recovered pre-burst tail
is at or below 0.1, the burst maximum is above 0.1, and the final three
post-burst samples are at or below 0.1. Kinesis and Flink lag must also show a
later drain. Otherwise record a failed drill and keep criterion (b) open. Do
not substitute Kinesis lag alone for Flink backpressure. Regardless of the
measurement verdict, continue immediately to cleanup.

## 10. Restore ECS and uninstall KEDA before the guard fires

First restore the known-good route:

```hcl
serving_target = "ecs"
```

`ARUN RUNS`:

```bash
PLAN_LABEL=wave4-w4-rollback-ecs
PLAN_FILE="$ARTIFACT_DIR/$PLAN_LABEL.tfplan"
PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$PLAN_LABEL.json"
scripts/plan_artifact.sh "$PLAN_LABEL" "$PLAN_FILE"
terraform -chdir=infra/terraform/envs/base show -no-color "$PLAN_FILE" \
  | tee "$ARTIFACT_DIR/$PLAN_LABEL.plan.txt"
test "$(shasum -a 256 "$PLAN_FILE" | awk '{print $1}')" = \
  "$(jq -r .plan_sha256 "$PLAN_SUMMARY")"
make apply-plan PLAN="$PLAN_FILE"
```

Verify ECS with one signed request. This POST is a live application action, so
Arun runs it even though it is used only as verification.

`ARUN RUNS`:

```bash
SERVING_API=$(terraform -chdir=infra/terraform/envs/base output -raw serving_api_endpoint)
SERVING_API="$SERVING_API" .venv/bin/python -c 'import json, os; from scripts.observe_phase5_scale import signed_inference_status; status, error = signed_inference_status(os.environ["SERVING_API"].rstrip("/") + "/v1/score-ais", os.environ.get("AWS_REGION", "us-east-1")); print(json.dumps({"http_status": status, "error": error})); raise SystemExit(0 if status == 200 and error is None else 1)' \
  > "$ARTIFACT_DIR/ecs-rollback-inference.json"
cat "$ARTIFACT_DIR/ecs-rollback-inference.json"
```

`ARUN RUNS`:

```bash
kubectl delete -f "$RENDERED_MANIFEST"
```

Then set:

```hcl
enable_phase5_keda = false
```

`ARUN RUNS`:

```bash
PLAN_LABEL=wave4-w4-uninstall-keda
PLAN_FILE="$ARTIFACT_DIR/$PLAN_LABEL.tfplan"
PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$PLAN_LABEL.json"
scripts/plan_artifact.sh "$PLAN_LABEL" "$PLAN_FILE"
terraform -chdir=infra/terraform/envs/base show -no-color "$PLAN_FILE" \
  | tee "$ARTIFACT_DIR/$PLAN_LABEL.plan.txt"
test "$(shasum -a 256 "$PLAN_FILE" | awk '{print $1}')" = \
  "$(jq -r .plan_sha256 "$PLAN_SUMMARY")"
make apply-plan PLAN="$PLAN_FILE"
```

Verify no Helm release remains in state and no KEDA pods remain:

```bash
terraform -chdir=infra/terraform/envs/base state list | rg 'helm_release' || true
kubectl get pods -n keda
```

Now set:

```hcl
enable_phase5_kubernetes_access = false
phase5_teardown_max_age_hours = 0
phase5_teardown_schedule_expression = "rate(5 minutes)"
```

`ARUN RUNS`:

```bash
PLAN_LABEL=wave4-w4-arm-live-fire
PLAN_FILE="$ARTIFACT_DIR/$PLAN_LABEL.tfplan"
PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$PLAN_LABEL.json"
scripts/plan_artifact.sh "$PLAN_LABEL" "$PLAN_FILE"
terraform -chdir=infra/terraform/envs/base show -no-color "$PLAN_FILE" \
  | tee "$ARTIFACT_DIR/$PLAN_LABEL.plan.txt"
test "$(shasum -a 256 "$PLAN_FILE" | awk '{print $1}')" = \
  "$(jq -r .plan_sha256 "$PLAN_SUMMARY")"
make apply-plan PLAN="$PLAN_FILE"
```

This is the criterion (f) proof. Do not invoke the Lambda directly. Follow its
read-only log stream and let Scheduler invoke it. The first successful tick
deletes node groups; a later tick deletes the cluster after node-group deletion
converges.

```bash
aws logs tail "/aws/lambda/$GUARD" --since 30m --follow \
  > "$ARTIFACT_DIR/guard-live-fire-follow.log" 2>&1 &
GUARD_LOG_PID=$!
cleanup_guard_log_tail() {
  kill "$GUARD_LOG_PID" 2>/dev/null || true
  wait "$GUARD_LOG_PID" 2>/dev/null || true
}
trap cleanup_guard_log_tail EXIT INT TERM

DELETION_CONFIRMED=false
for _ in {1..80}; do
  if CLUSTER_STATUS=$(aws eks describe-cluster \
    --name "$CLUSTER" \
    --query cluster.status \
    --output text 2>&1); then
    printf 'cluster status: %s\n' "$CLUSTER_STATUS" \
      | tee -a "$ARTIFACT_DIR/guard-live-fire-poll.txt"
    if NODEGROUPS=$(aws eks list-nodegroups --cluster-name "$CLUSTER" 2>&1); then
      printf 'node groups: %s\n' "$NODEGROUPS" \
        | tee -a "$ARTIFACT_DIR/guard-live-fire-poll.txt"
    else
      LIST_STATUS=$?
      if printf '%s\n' "$NODEGROUPS" | rg -q 'ResourceNotFoundException'; then
        DELETION_CONFIRMED=true
        break
      fi
      printf 'list-nodegroups failed: %s\n' "$NODEGROUPS" >&2
      exit "$LIST_STATUS"
    fi
  else
    DESCRIBE_STATUS=$?
    if printf '%s\n' "$CLUSTER_STATUS" | rg -q 'ResourceNotFoundException'; then
      DELETION_CONFIRMED=true
      break
    fi
    printf 'describe-cluster failed: %s\n' "$CLUSTER_STATUS" >&2
    exit "$DESCRIBE_STATUS"
  fi
  sleep 30
done
cleanup_guard_log_tail
trap - EXIT INT TERM
test "$DELETION_CONFIRMED" = true
printf 'cluster deletion confirmed by ResourceNotFoundException at %s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  | tee "$ARTIFACT_DIR/guard-live-fire.txt"
```

Save the final logs:

```bash
aws logs tail "/aws/lambda/$GUARD" --since 60m \
  | tee "$ARTIFACT_DIR/guard-live-fire.log"
```

## 11. Reconcile state and remove all W4 resources

The guard deletes the node group and cluster outside Terraform. Remove only
those two confirmed-missing objects from Terraform state.

```bash
terraform -chdir=infra/terraform/envs/base state list \
  | rg 'module\.eks_(cluster|node_group)\[0\]\.aws_eks_(cluster|node_group)\.this'
```

The expected exact addresses are:

```text
module.eks_cluster[0].aws_eks_cluster.this
module.eks_node_group[0].aws_eks_node_group.this
```

`ARUN RUNS`, only after `describe-cluster` reports not found:

```bash
terraform -chdir=infra/terraform/envs/base state rm \
  'module.eks_cluster[0].aws_eks_cluster.this' \
  'module.eks_node_group[0].aws_eks_node_group.this'
```

Stop the Managed Flink application before the final Terraform apply.
`ARUN RUNS`:

```bash
aws kinesisanalyticsv2 stop-application --application-name "$FLINK_APP"

for _ in {1..40}; do
  FLINK_STATUS=$(aws kinesisanalyticsv2 describe-application \
    --application-name "$FLINK_APP" \
    --query ApplicationDetail.ApplicationStatus \
    --output text)
  test "$FLINK_STATUS" = "READY" && break
  case "$FLINK_STATUS" in
    RUNNING|STOPPING|FORCE_STOPPING) sleep 15 ;;
    *) printf 'unexpected Flink status: %s\n' "$FLINK_STATUS" >&2; exit 1 ;;
  esac
done
test "$FLINK_STATUS" = "READY"
aws kinesisanalyticsv2 describe-application \
  --application-name "$FLINK_APP" \
  | tee "$ARTIFACT_DIR/flink-stopped.json"
```

Set the safe resting posture:

```hcl
enable_nat                         = false
enable_nightly_teardown            = true
teardown_dry_run                   = false
enable_phase5                      = false
enable_phase5_kubernetes_access    = false
enable_phase5_keda                 = false
phase5_endpoint_public_access      = false
phase5_public_access_cidrs         = []
phase5_node_desired_size           = 0
phase5_guard_dry_run               = false
phase5_teardown_max_age_hours      = 4
phase5_teardown_schedule_expression = "rate(30 minutes)"
phase5_keep_alive_until            = ""
serving_target                     = "ecs"
flink_code_s3_key                  = ""
```

`ARUN RUNS`:

```bash
PLAN_LABEL=wave4-w4-final-cleanup
PLAN_FILE="$ARTIFACT_DIR/$PLAN_LABEL.tfplan"
PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$PLAN_LABEL.json"
scripts/plan_artifact.sh "$PLAN_LABEL" "$PLAN_FILE"
terraform -chdir=infra/terraform/envs/base show -no-color "$PLAN_FILE" \
  | tee "$ARTIFACT_DIR/$PLAN_LABEL.plan.txt"
test "$(shasum -a 256 "$PLAN_FILE" | awk '{print $1}')" = \
  "$(jq -r .plan_sha256 "$PLAN_SUMMARY")"
```

The plan may delete remaining Phase 5 resources, including the NLB, target
group, OIDC provider, EKS IAM roles, guard, Scheduler, log groups, and CMKs
scheduled for deletion. It may delete the Managed Flink application after the
code key is cleared. It must not delete or replace Phase 1 state stores.

`ARUN RUNS`:

```bash
make apply-plan PLAN="$PLAN_FILE"
```

## 12. Final verification and evidence handoff

The signed inference below is a live application POST. `ARUN RUNS`:

```bash
set -euo pipefail
aws eks list-clusters | tee "$ARTIFACT_DIR/eks-after.json"
aws elbv2 describe-load-balancers \
  --query 'LoadBalancers[?LoadBalancerName == `harbormaster-base-eks`]' \
  | tee "$ARTIFACT_DIR/nlb-after.json"
aws ec2 describe-nat-gateways \
  --filter Name=tag:Project,Values=harbormaster Name=state,Values=available,pending \
  | tee "$ARTIFACT_DIR/nat-after.json"
aws ec2 describe-addresses \
  --filters Name=tag:Project,Values=harbormaster \
  | tee "$ARTIFACT_DIR/eip-after.json"
aws scheduler list-schedules \
  --name-prefix "$SCHEDULE" \
  | tee "$ARTIFACT_DIR/guard-schedule-after.json"
aws kinesisanalyticsv2 list-applications \
  | tee "$ARTIFACT_DIR/flink-after.json"
jq -e --arg cluster "$CLUSTER" '.clusters | index($cluster) == null' \
  "$ARTIFACT_DIR/eks-after.json"
jq -e 'length == 0' "$ARTIFACT_DIR/nlb-after.json"
jq -e '.NatGateways | length == 0' "$ARTIFACT_DIR/nat-after.json"
jq -e '.Addresses | length == 0' "$ARTIFACT_DIR/eip-after.json"
jq -e --arg schedule "$SCHEDULE" \
  '.Schedules | all(.Name != $schedule)' \
  "$ARTIFACT_DIR/guard-schedule-after.json"
jq -e --arg application "$FLINK_APP" \
  '.ApplicationSummaries | all(.ApplicationName != $application)' \
  "$ARTIFACT_DIR/flink-after.json"
TEARDOWN_LAMBDA=$(terraform -chdir=infra/terraform/envs/base output -raw teardown_lambda_name)
aws lambda get-function-configuration \
  --function-name "$TEARDOWN_LAMBDA" \
  | tee "$ARTIFACT_DIR/nightly-teardown-lambda.json"
aws scheduler get-schedule \
  --name harbormaster-base-nightly-teardown \
  | tee "$ARTIFACT_DIR/nightly-teardown-schedule.json"
jq -e '.Environment.Variables.DRY_RUN == "false"' \
  "$ARTIFACT_DIR/nightly-teardown-lambda.json"
jq -e '.State == "ENABLED"' \
  "$ARTIFACT_DIR/nightly-teardown-schedule.json"

SERVING_API=$(terraform -chdir=infra/terraform/envs/base output -raw serving_api_endpoint)
SERVING_API="$SERVING_API" .venv/bin/python -c 'import json, os; from scripts.observe_phase5_scale import signed_inference_status; status, error = signed_inference_status(os.environ["SERVING_API"].rstrip("/") + "/v1/score-ais", os.environ.get("AWS_REGION", "us-east-1")); print(json.dumps({"http_status": status, "error": error})); raise SystemExit(0 if status == 200 and error is None else 1)' \
  > "$ARTIFACT_DIR/final-ecs-inference.json"
cat "$ARTIFACT_DIR/final-ecs-inference.json"
VERIFY_LABEL=wave4-w4-verified-clean
VERIFY_PLAN_FILE="$ARTIFACT_DIR/$VERIFY_LABEL.tfplan"
VERIFY_PLAN_SUMMARY="docs/plan-artifacts/$(date -u +%F)-$VERIFY_LABEL.json"
scripts/plan_artifact.sh "$VERIFY_LABEL" "$VERIFY_PLAN_FILE"
test "$(shasum -a 256 "$VERIFY_PLAN_FILE" | awk '{print $1}')" = \
  "$(jq -r .plan_sha256 "$VERIFY_PLAN_SUMMARY")"
jq -e '
  .add == 0 and .change == 0 and .destroy == 0 and
  all(.resource_changes[]?; .actions == ["no-op"])
' "$VERIFY_PLAN_SUMMARY"
```

Required final verdicts:

- No Harbormaster EKS cluster, serving NLB, NAT gateway, Elastic IP, or Phase 5
  guard schedule remains.
- The Managed Flink application is absent after its code key is cleared.
- The API Gateway route is back on ECS and a signed `/v1/score-ais` inference
  returns 200.
- Nightly teardown remains enabled and wet (`teardown_dry_run = false`).
- The final Terraform plan has no unexplained drift.

Create a sanitized handoff directory from an explicit file-type allowlist. The
binary plans remain local because they can contain resolved sensitive values.
The presigned Flink dashboard URL stays only in the shell environment and must
not appear in any handoff file.

```bash
HANDOFF_DIR="$ARTIFACT_DIR-sanitized"
test ! -e "$HANDOFF_DIR"
mkdir -p "$HANDOFF_DIR/plan-summaries"
find "$ARTIFACT_DIR" -maxdepth 1 -type f \
  \( -name '*.json' -o -name '*.jsonl' -o -name '*.txt' \
     -o -name '*.yaml' -o -name '*.log' \) \
  -exec cp {} "$HANDOFF_DIR/" \;
find docs/plan-artifacts -maxdepth 1 -type f -name '*-wave4-w4-*.json' \
  -exec cp {} "$HANDOFF_DIR/plan-summaries/" \;
test -z "$(find "$HANDOFF_DIR" -type f -name '*.tfplan' -print -quit)"
if rg -n -i \
  'X-Amz-(Credential|Signature|Security-Token)=|aws_(access_key_id|secret_access_key|session_token)|AKIA[0-9A-Z]{16}' \
  "$HANDOFF_DIR"; then
  printf 'potential credential or presigned URL found; sanitize before handoff\n' >&2
  exit 1
fi
```

Review the allowlisted files, then hand only `$HANDOFF_DIR` to Codex. Only then
create `docs/drills/M3_backpressure_loadtest.md`, update the Phase 5 status,
and ground war story P37 if a real SLO breach occurred. Every number in those
documents must trace to a file in the sanitized handoff directory.

## Deferred, non-gating live work

Run these in separate scheduled windows, never as opportunistic additions to
W4:

- Retry Debezium registration on AWS with the corrected base64 transport.
- Boundary Part C least-privilege proof under the platform role.
- Live RDS tenant isolation drill.
- Live Bedrock prompt-leakage drill.
- Live SageMaker canary shift and rollback.
