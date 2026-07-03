# Harbormaster AWS setup (gate G0 on-ramp)

The one-time AWS setup that unblocks gate G0 and every AWS gate in
[`docs/phases/PHASE_1.md`](phases/PHASE_1.md). It turns that file's 8-step prose
into an ordered, mostly-scripted runbook so your hands-on work is only the
console-only account hygiene. The hard cost cap is **$75/month**, enforced by the
FinOps module (an IAM deny policy attached to the platform role on breach), with a
$30 soft budget alerting at $5 / $15 / $25 actual and $30 forecast.

Nothing here is irreversible without your say-so: the scripted step creates only an
IAM role and an empty S3 bucket, and `make apply` prompts before it creates anything
billable.

## What is automated vs yours

| Stage | Who | How |
|---|---|---|
| Account hygiene (root MFA, admin identity, CLI) | you (console) | step 1 |
| Platform role + state bucket | scripted | `infra/aws/bootstrap.sh` (step 2) |
| Phase 0 stand-up (network, state stores, FinOps) | terraform | `make apply` (step 3) |
| Remote state migration | you + terraform | edit `backend.tf`, `init -migrate-state` (step 4) |
| Guardrail proof | you | over-spend + teardown drill (step 5) |

Local prerequisites (already verified present on this machine): AWS CLI v2, Terraform
>= 1.6, docker, jq. Region is `us-east-1` throughout (Budgets and Cost Explorer report
there regardless).

## Step 1 - Account hygiene (console only, cannot be scripted)

1. Enable MFA on the root user.
2. Create an admin identity you will actually use: an IAM user with AdministratorAccess
   (make an access key for it), or IAM Identity Center (SSO). This is your break-glass
   identity; you run Terraform as this, not as root and not as the platform role.
3. Configure the CLI as that admin: `aws configure` (or `aws configure sso`).

**Do NOT configure the CLI with root access keys.** Root keys bypass the $75 FinOps
guardrail (the deny action attaches to the platform role, not to root) and are the top
AWS security risk. If you already created them, delete them once the admin works:
IAM console -> account menu -> Security credentials -> Access keys.

**Checksum:** `aws sts get-caller-identity` shows an ARN ending in `:user/<name>` or an
SSO role, **not** `:root`; `aws configure get region` returns `us-east-1`.

## Step 2 - Platform role + state bucket (scripted)

Dry-run first (changes nothing, needs no credentials), then run for real:

```bash
bash infra/aws/bootstrap.sh --dry-run
bash infra/aws/bootstrap.sh          # confirms each mutating step; use --yes to skip prompts
```

This creates:
- IAM role **`harbormaster-platform`** (trust = your account with MFA; PowerUserAccess +
  an IAM-management inline policy from `infra/aws/harbormaster-platform-permissions.json`).
  It is the `platform_role_name` in `terraform.tfvars` and the target the $75 deny
  action attaches to. Deliberately not your admin identity, so a freeze never locks you out.
- S3 bucket **`harbormaster-tfstate-<account-id>`** (versioned, AES256, public access
  blocked), the dedicated remote-state store, kept separate from the data lake.

The script prints the exact `backend.tf` values to use in step 4.

**Checksum:** `aws iam get-role --role-name harbormaster-platform` returns the role;
`aws s3api get-bucket-versioning --bucket harbormaster-tfstate-<account-id>` shows
`Enabled`.

## Step 3 - Phase 0 apply (terraform)

`terraform.tfvars` is pre-filled; confirm only `alert_email`. Then:

```bash
make fmt        # terraform fmt -recursive
make validate   # terraform validate (-backend=false, no creds needed)
make plan       # review the resource plan against the $75 cap
make apply      # prompts 'yes'; creates network + state stores + FinOps guardrails
```

Click the one-time SNS confirmation email AWS sends to `alert_email`, or you get no alerts.

**Checksum (gate G0 core):** the $75 budget action, the cost-anomaly monitor, and the
teardown Lambda all exist; `terraform -chdir=infra/terraform/envs/base output` shows
`lake_bucket_name`, `tf_state_lock_table_name`, `budget_alerts_sns_topic_arn`,
`spend_freeze_policy_arn`, `teardown_lambda_name`. Enable Cost Explorer in the console
(takes ~24h to populate).

## Step 4 - Migrate to remote state

Using the values `bootstrap.sh` printed (and confirming the lock-table name from
`terraform output tf_state_lock_table_name`):

1. In `infra/terraform/envs/base/backend.tf`, comment out the `backend "local"` block
   and uncomment the `backend "s3"` block, filling in the literal bucket + lock-table.
2. `terraform -chdir=infra/terraform/envs/base init -migrate-state` (Terraform copies
   local state into S3).

**Checksum:** state now lives in the S3 bucket; a fresh `make plan` shows no drift.

## Step 5 - Guardrail proof (gate G0 final)

1. Simulate a small over-spend (or temporarily lower the budget threshold) and confirm
   the IAM-deny action blocks new resource creation on the platform role.
2. Run the teardown Lambda with `DRY_RUN=true` and confirm the SNS cost summary arrives.

**Checksum:** the deny action blocks new resource creation; the teardown Lambda dry-run
logs what it would stop and posts the SNS summary.

## Gate G0 is green

With steps 1-5 done, gate G0 passes and the AWS gates unlock. Continue at PHASE_1.md
1.3 (Terraform Phase 1 modules) onward. The separate Ray/rate submission is an
independent precondition tracked in PHASE_1.md, not part of this runbook.

## Files this runbook uses

- `infra/aws/bootstrap.sh` - the scripted step-2 scaffolding (idempotent, `--dry-run`).
- `infra/aws/harbormaster-platform-trust.json` / `harbormaster-platform-permissions.json`
  - the platform role's trust + permissions.
- `infra/terraform/envs/base/terraform.tfvars` - pre-filled (gitignored).
- `infra/terraform/envs/base/backend.tf` - the local-to-S3 migration (step 4).
- `Makefile` - `fmt` / `validate` / `plan` / `apply` / `destroy` / `cost`.
