# Runbook: apply the IAM permissions boundary and API Gateway hardening

Arun-run, in a dedicated AWS window. This applies the security infra the audit
branch authored but deliberately did not apply (war story P32, the two-sided
contract). Account 645322802947, region us-east-1. Nothing here runs
automatically; each step is a command you run and verify.

## What this applies, and what it does not

- Applies: the `harbormaster-permissions-boundary` policy and the hardened,
  boundary-gated inline policy on the `harbormaster-platform` deploy role
  (Part A, free and standing), plus the `permissions_boundary` on every module
  role and the API Gateway authorizer + throttling + access logging (Part B,
  during a billable Phase 1 window).
- Does NOT apply: the customer-managed KMS key. `modules/kms` is now authored
  behind `enable_cmk` (default false, so the default plan stays a zero diff)
  but the flag stays off here; flip it and apply in a later window. It is out
  of scope here.

## Identities (read before running anything)

- `arun-admin`: your IAM user with AdministratorAccess and MFA. Break-glass.
  Run every apply below as this identity. Admin is NOT boundary-conditioned, so
  `CreateRole` always succeeds and you cannot lock yourself out.
- `harbormaster-platform`: the scoped deploy role and the target the $75 FinOps
  budget action attaches a deny to on breach. Part A hardens its policy. Do not
  switch your deploy identity to it until Part C proves it works.

## Part A: harden the deploy identity (free, standing, do this first)

This closes the `iam:*`-on-`Resource "*"` escalation. It creates no billable
resource, so do it independently of any demo window.

1. Preview, changing nothing:
   ```
   bash infra/aws/bootstrap.sh --dry-run
   ```
   Note: `--dry-run` cannot check whether the role already exists (no live
   call), so it always prints Step 2 as a create plan. On the real run below,
   because the role already exists from the Phase 0 bootstrap, Step 2 takes the
   reconcile path instead (see the trap note).

2. Run for real (as `arun-admin`), confirming each step:
   ```
   bash infra/aws/bootstrap.sh
   ```
   Step 1 creates the `harbormaster-permissions-boundary` policy. Step 2, on the
   existing `harbormaster-platform` role, reconciles its policies:
   re-attaches `PowerUserAccess` and `put-role-policy`s the boundary-gated
   `harbormaster-iam-management` inline policy, overwriting the old escalation
   version.

   Trap this fixes: the previous `bootstrap.sh` skipped an existing role
   ("leaving it unchanged"), which would have left the old `iam:*`-on-`*` inline
   policy in place. The reconcile path replaces it.

3. Verify the escalation is closed:
   ```
   aws iam get-role-policy --role-name harbormaster-platform \
     --policy-name harbormaster-iam-management \
     --query 'PolicyDocument.Statement[?Effect==`Allow`]'
   ```
   No Allow statement should grant a write `iam:*` action on `Resource "*"`.
   IAM management should be scoped to `role/policy/instance-profile
   harbormaster-*` and conditioned on the boundary. Confirm the boundary policy
   exists:
   ```
   aws iam get-policy --policy-arn arn:aws:iam::645322802947:policy/harbormaster-permissions-boundary
   ```

## Part B: module-role boundaries + API Gateway hardening (billable Phase 1 window)

The apigw hardening and the Phase 1 module roles only exist when
`enable_phase1 = true`, so this is a demo-window apply with real cost (RDS +
Fargate + API Gateway while up). The `permissions_boundary_name` default is
already correct, so no tfvars change is needed for the boundary itself.

1. In `infra/terraform/envs/base/terraform.tfvars` set:
   ```
   enable_phase1 = true
   ```

2. Plan as `arun-admin` and inspect:
   ```
   make plan
   ```
   Confirm in the plan that every `aws_iam_role` has `permissions_boundary` set
   to the boundary ARN and none is created without it, and that the API Gateway
   stage shows the default-route throttling, the `access_log_settings`, and the
   route `authorization_type = AWS_IAM`.

3. Apply as `arun-admin` (never as the platform role yet):
   ```
   make apply
   ```

4. Verify live:
   ```
   for r in $(aws iam list-roles --query "Roles[?starts_with(RoleName, 'harbormaster-base-')].RoleName" --output text); do
     printf '%s\t%s\n' "$r" "$(aws iam get-role --role-name "$r" --query 'Role.PermissionsBoundary.PermissionsBoundaryArn' --output text)"
   done
   ```
   Every `harbormaster-base-*` role should print the boundary ARN, none `None`.
   Then confirm the API Gateway front door is no longer anonymous: a request
   without SigV4 signing is rejected, and the stage has an access-log group and
   throttling. A signed request (or the demo client) still succeeds.

5. Teardown (return to ~$0 standing, keep the Part A win):
   ```
   # set enable_phase1 = false in terraform.tfvars, then:
   make apply
   ```
   Use `enable_phase1 = false` + `make apply`, not `make destroy` on base. The
   boundary policy and the hardened `harbormaster-platform` role from Part A are
   free and stay in place.

## Part C: prove least-privilege (optional, later)

Once Parts A and B are clean, switch the deploy identity from `arun-admin` to
the boundary-gated `harbormaster-platform` role and re-run a Phase 1 plan/apply
to prove it can create the bounded roles but cannot escalate. Keep `arun-admin`
as break-glass and do not remove AdministratorAccess from it until an apply
under the platform role is proven. The boundary also denies removing or
swapping a role's `PermissionsBoundary`, so once bounded, only `arun-admin` can
alter boundaries.

## Rollback

- Part A: `aws iam put-role-policy` the previous inline policy back onto
  `harbormaster-platform` (keep a copy first), or detach and let the create path
  re-run. The break-glass `arun-admin` is unaffected either way.
- Part B: `enable_phase1 = false` + `make apply` removes the Phase 1 resources
  (and their roles) cleanly; the state is back to Phase-0-only.

## Cost

- Part A: $0 (IAM policies and role attachments are free).
- Part B: a Phase 1 demo window (RDS db.t4g.micro + two Fargate tasks + API
  Gateway HTTP API + optional Flink). Small per hour; tear down after. The $75
  FinOps hard cap and the nightly teardown Lambda remain in force.
- WAF is variable-gated off by default (`enable_waf = false`); turning it on
  adds standing cost. CMK (authored behind `enable_cmk`, default false) is
  roughly $1 per key per month plus usage once enabled.
