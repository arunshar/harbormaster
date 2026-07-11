# Runbook: merge the audit PR and apply the deferred infra

Arun-run. The two things left after the AB-masterclass audit branch: merge PR #2
into `master`, and later apply the deferred IAM boundary + API Gateway hardening
in a dedicated AWS window. Account 645322802947, region us-east-1.

State at authoring time: PR #2 (`feat/ab-masterclass-audit` -> `phase4-flywheel`)
is MERGEABLE / CLEAN with all five checks green; `master` is not branch-protected;
PR #1 is `phase4-flywheel -> master`.

## Part 1: merge PR #2 into master (about 10 minutes, no cost)

Why one merge, not two: `feat/ab-masterclass-audit` branched off
`phase4-flywheel`, so it contains every commit `phase4-flywheel` has, plus
phases 0-4, the audit, the CI fixes, the boundary threading, and the runbooks. It
is ~101 commits ahead of `master` and `phase4-flywheel` is its ancestor. So merge
the one superset PR into `master` and close the redundant PR #1.

### 1.0 Pre-flight
```
gh pr view 2 --repo arunshar/harbormaster --json mergeable,mergeStateStatus,baseRefName
gh pr checks 2 --repo arunshar/harbormaster
```
Expect `mergeable: MERGEABLE`, `mergeStateStatus: CLEAN`, all five checks `pass`.
If any check is not green, stop and look before merging.

### 1.1 Retarget PR #2 to master
```
gh pr edit 2 --repo arunshar/harbormaster --base master
gh pr view 2 --repo arunshar/harbormaster --json mergeable,mergeStateStatus
```
This only changes the merge target. After retargeting the diff GitHub shows is the
whole audit branch (everything not yet in `master`). Confirm it is still clean.

### 1.2 Review the diff (recommended)
```
gh pr view 2 --repo arunshar/harbormaster --web
```
A final sanity pass, not a blocker; the one real gate (checkov) is green.

### 1.3 Merge with a merge commit
```
gh pr merge 2 --repo arunshar/harbormaster --merge
```
Use `--merge` (a merge commit), not `--squash`, so the per-phase commits and the
war-story trail survive in `master`. If `gh` asks to delete the source branch,
keep it for now (answer no, or add `--delete-branch=false`); the branch is
harmless and useful as a reference.

### 1.4 Close PR #1 as superseded
```
gh pr close 1 --repo arunshar/harbormaster --comment "Superseded by #2 (feat/ab-masterclass-audit contains all of phase4-flywheel and merged to master)."
```
PR #1's commits are now in `master` via #2, so closing it (not merging) is correct.

### 1.5 Sync local master
```
cd ~/code/harbormaster
git checkout master
git pull origin master
git log --oneline -5    # the merge commit should be at the top
```

### Troubleshooting
- Retarget reports a conflict (unlikely, base is an ancestor):
  `git checkout feat/ab-masterclass-audit && git merge origin/master`, resolve,
  push, then merge.
- Deleted the branch by accident: the branch is only a pointer; the commits are in
  `master`, nothing is lost.

## Part 2: apply the IAM boundary + API Gateway hardening (dedicated AWS window)

Full detail with per-step verification, rollback, and cost is in
[IAM_BOUNDARY_APPLY.md](IAM_BOUNDARY_APPLY.md). This is the condensed sequence. Do
it in its own block of time, not squeezed around a call, because Part B spins up
billable AWS and needs a clean teardown.

Prerequisites: no VPN (this is AWS, not MSI); AWS CLI configured as `arun-admin`
with MFA (`aws sts get-caller-identity` shows `.../user/arun-admin`). Every apply
runs as `arun-admin`, which is not boundary-conditioned and so cannot lock you out
of `CreateRole`.

### 2.A Deploy-identity hardening (free, standing, do first)
Closes the `iam:*`-on-`Resource "*"` escalation. No billable resource.
```
bash infra/aws/bootstrap.sh --dry-run    # preview; prints Step 2 as a create plan
bash infra/aws/bootstrap.sh              # real run: creates the boundary policy and,
                                         # because the role exists, RECONCILES its
                                         # inline policy to the boundary-gated version
```
Verify no Allow grants write `iam:*` on `Resource "*"`:
```
aws iam get-role-policy --role-name harbormaster-platform \
  --policy-name harbormaster-iam-management \
  --query 'PolicyDocument.Statement[?Effect==`Allow`]'
aws iam get-policy --policy-arn arn:aws:iam::645322802947:policy/harbormaster-permissions-boundary
```

### 2.B Module-role boundaries + apigw hardening (billable Phase 1 window)
Count-gated on `enable_phase1`, so this is a demo-window apply with real cost
(RDS + two Fargate tasks + API Gateway while up). The `permissions_boundary_name`
default is already correct.
```
# 1. in infra/terraform/envs/base/terraform.tfvars set: enable_phase1 = true
make plan     # confirm every aws_iam_role shows permissions_boundary; none without it;
              # apigw stage has throttling, access_log_settings, authorization_type AWS_IAM
make apply    # as arun-admin
```
Verify every role is bounded:
```
for r in $(aws iam list-roles --query "Roles[?starts_with(RoleName, 'harbormaster-base-')].RoleName" --output text); do
  printf '%s\t%s\n' "$r" "$(aws iam get-role --role-name "$r" --query 'Role.PermissionsBoundary.PermissionsBoundaryArn' --output text)"
done
```
Every `harbormaster-base-*` role prints the boundary ARN, none `None`. Confirm the
API front door rejects an unsigned request and has an access-log group + throttling.

Teardown (return to ~$0 standing, keep the Part A win):
```
# set enable_phase1 = false in terraform.tfvars, then:
make apply    # not make destroy on base
```
The boundary policy and hardened platform role from Part A are free and stay.

### 2.C Prove least-privilege (optional, later)
Switch the deploy identity from `arun-admin` to the boundary-gated
`harbormaster-platform` role and re-run a Phase 1 plan/apply to prove it can create
the bounded roles but cannot escalate. Keep `arun-admin` as break-glass; do not
remove AdministratorAccess from it until an apply under the platform role is proven.

### CMK
Authored, not applied: `modules/kms` (key with rotation and a 7-day deletion
window, alias/harbormaster-base, wired to S3/RDS/DynamoDB/log groups behind the
`enable_cmk` flag, default false so the default plan stays a zero diff). Not part
of this apply; flip `enable_cmk = true` and apply in a later window at roughly
$1 per key per month plus usage. Setting the key on an EXISTING RDS instance
forces replacement, so enable it only on a fresh Phase 1 window.

### Cost and safety
Part A is $0. Part B is a short billable window (small per hour), always torn down
after. The $75 FinOps hard cap and the nightly teardown Lambda stay in force.
