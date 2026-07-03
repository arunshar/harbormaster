#!/usr/bin/env bash
#
# infra/aws/bootstrap.sh
#
# One-time AWS scaffolding for Harbormaster gate G0 (the on-ramp described in
# docs/AWS_SETUP.md and docs/phases/PHASE_1.md). It creates ONLY the two things
# Terraform cannot bootstrap itself:
#
#   1. the "harbormaster-platform" IAM role  (the $75 budget action attaches its
#      deny policy to THIS role on breach, so it must exist before `make apply`;
#      it is deliberately NOT your admin identity, so a spend-freeze cannot lock
#      you out of `terraform destroy`), and
#   2. a dedicated, versioned, encrypted, public-access-blocked S3 bucket for
#      remote Terraform state  (kept separate from the data lake, per backend.tf).
#
# It does NOT run `terraform apply`, touch the data lake, or create any
# spend-incurring streaming/compute resource. Everything here is free or
# negligible (an IAM role and an empty S3 bucket).
#
# Idempotent: re-running skips anything that already exists.
#
# Usage:
#   bash infra/aws/bootstrap.sh --dry-run     # print the plan, change nothing (no creds needed)
#   bash infra/aws/bootstrap.sh               # interactive, confirm each mutating step
#   bash infra/aws/bootstrap.sh --yes         # non-interactive (assume yes)
#   bash infra/aws/bootstrap.sh --region us-east-1 --suffix myuniq
#
set -euo pipefail

PROJECT="harbormaster"
REGION="us-east-1"
ROLE_NAME="harbormaster-platform"
# The DynamoDB lock table is created by Phase 0 Terraform (state_stores module);
# we only PRINT its name here for the later backend-migration step.
LOCK_TABLE="harbormaster-base-tf-state-lock"
DRY_RUN=0
ASSUME_YES=0
SUFFIX=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  grep -E '^#( |$)' "$0" | sed -E 's/^# ?//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)       DRY_RUN=1 ;;
    --yes|-y)        ASSUME_YES=1 ;;
    --region)        REGION="${2:?--region needs a value}"; shift ;;
    --suffix)        SUFFIX="${2:?--suffix needs a value}"; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; echo "run with --help" >&2; exit 2 ;;
  esac
  shift
done

# ---- output helpers ----------------------------------------------------------
log()  { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
# run: echo the command, then execute it unless --dry-run.
run() {
  printf '    $ %s\n' "$*"
  [ "$DRY_RUN" -eq 1 ] && return 0
  "$@"
}
# confirm: yes automatically under --yes or --dry-run; otherwise prompt.
confirm() {
  { [ "$ASSUME_YES" -eq 1 ] || [ "$DRY_RUN" -eq 1 ]; } && return 0
  printf '    %s [y/N] ' "$1"
  read -r _ans
  [ "$_ans" = "y" ] || [ "$_ans" = "Y" ]
}
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing required tool: $1" >&2; exit 1; }; }

# ---- preflight ---------------------------------------------------------------
log "Preflight: required tools + AWS identity + region ($REGION)"
need aws
need jq
info "aws:       $(aws --version 2>&1 | head -1)"

if ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)"; then
  info "AWS account: $ACCOUNT_ID"
  CALLER="$(aws sts get-caller-identity --query Arn --output text 2>/dev/null || echo '?')"
  info "caller ARN:  $CALLER"
else
  if [ "$DRY_RUN" -eq 1 ]; then
    ACCOUNT_ID="__ACCOUNT_ID__"
    info "no AWS credentials configured; dry-run continues with a placeholder account id"
  else
    echo "    ERROR: 'aws sts get-caller-identity' failed." >&2
    echo "    Configure the CLI first (see docs/AWS_SETUP.md, step 1): aws configure" >&2
    exit 1
  fi
fi

[ -n "$SUFFIX" ] || SUFFIX="$ACCOUNT_ID"
STATE_BUCKET="${PROJECT}-tfstate-${SUFFIX}"

# ---- step 1: platform IAM role ----------------------------------------------
log "Step 1: IAM role '$ROLE_NAME' (the \$75 deny-on-breach target; NOT your admin identity)"
if [ "$DRY_RUN" -eq 0 ] && aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  info "role already exists; leaving it unchanged"
else
  info "plan: create the role (trust = this account's identities, MFA required),"
  info "      attach the AWS-managed PowerUserAccess policy, and add the IAM-management"
  info "      inline policy from harbormaster-platform-permissions.json"
  if confirm "create IAM role '$ROLE_NAME'?"; then
    TRUST_JSON="$(jq --arg a "$ACCOUNT_ID" \
      '.Statement[0].Principal.AWS = ("arn:aws:iam::" + $a + ":root")' \
      "$SCRIPT_DIR/harbormaster-platform-trust.json")"
    run aws iam create-role \
      --role-name "$ROLE_NAME" \
      --assume-role-policy-document "$TRUST_JSON" \
      --description "Harbormaster platform/deploy role; the \$75 budget action attaches a deny policy here on breach" \
      --tags "Key=Project,Value=${PROJECT}"
    run aws iam attach-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-arn "arn:aws:iam::aws:policy/PowerUserAccess"
    run aws iam put-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "harbormaster-iam-management" \
      --policy-document "file://$SCRIPT_DIR/harbormaster-platform-permissions.json"
    info "done."
  else
    info "skipped."
  fi
fi

# ---- step 2: terraform state bucket -----------------------------------------
log "Step 2: Terraform state bucket 's3://$STATE_BUCKET' (versioned, encrypted, private)"
if [ "$DRY_RUN" -eq 0 ] && aws s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1; then
  info "bucket already exists; leaving it unchanged"
else
  info "plan: create the bucket in $REGION, then enable versioning, AES256 default"
  info "      encryption, and a full public-access block"
  if confirm "create S3 bucket '$STATE_BUCKET'?"; then
    # us-east-1 must NOT pass a LocationConstraint; every other region must.
    if [ "$REGION" = "us-east-1" ]; then
      run aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$REGION"
    else
      run aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$REGION" \
        --create-bucket-configuration "LocationConstraint=$REGION"
    fi
    run aws s3api put-bucket-versioning --bucket "$STATE_BUCKET" \
      --versioning-configuration "Status=Enabled"
    run aws s3api put-bucket-encryption --bucket "$STATE_BUCKET" \
      --server-side-encryption-configuration \
      '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
    run aws s3api put-public-access-block --bucket "$STATE_BUCKET" \
      --public-access-block-configuration \
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    info "done."
  else
    info "skipped."
  fi
fi

# ---- step 3: print the backend.tf values ------------------------------------
log "Step 3: values for the remote backend (edit infra/terraform/envs/base/backend.tf AFTER 'make apply')"
cat <<EOF
    Once Phase 0 is applied (so the lock table exists), migrate state:
      1. comment out the backend "local" block
      2. uncomment the backend "s3" block and set:
           bucket         = "$STATE_BUCKET"
           key            = "base/terraform.tfstate"
           region         = "$REGION"
           dynamodb_table = "$LOCK_TABLE"   # confirm via: terraform -chdir=infra/terraform/envs/base output tf_state_lock_table_name
           encrypt        = true
      3. terraform -chdir=infra/terraform/envs/base init -migrate-state

EOF

log "Bootstrap ${DRY_RUN:+plan }complete."
if [ "$DRY_RUN" -eq 1 ]; then
  info "This was a DRY RUN. Re-run without --dry-run to create the role and bucket."
else
  info "Next: confirm alert_email in terraform.tfvars, then 'make plan' and 'make apply'."
fi
info "Full runbook: docs/AWS_SETUP.md"
