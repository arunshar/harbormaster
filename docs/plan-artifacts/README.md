# Plan artifacts

Committed summaries of `terraform plan` for the `infra/terraform/envs/base`
root, one JSON file per plan, named `<UTC-date>-<label>.json`.

## Why this directory exists

Harbormaster's audit trail had a known gap: applies were run from a local
terminal and reviewed live, but no plan artifact was ever committed, so a
reviewer could not later see what a given apply window was expected to change.
This directory closes that gap. Each file is the reviewable record of what a
plan proposed at a point in time, captured before the corresponding apply.

## How artifacts are produced

```bash
scripts/plan_artifact.sh <label> [local-plan-file]
# Example:
scripts/plan_artifact.sh phase4-flywheel artifacts/phase4.tfplan
```

The script runs `terraform plan -out=<local-plan-file>` against envs/base,
converts the plan with `terraform show -json`, and writes a summary here. If no
local plan path is supplied, the binary remains temporary for compatibility
with older plan-only workflows.

```json
{
  "generated_utc": "...",
  "label": "...",
  "plan_sha256": "...",
  "add": 0,
  "change": 0,
  "destroy": 0,
  "resource_changes": [{"address": "module....", "actions": ["create"]}]
}
```

A replace counts as both an add and a destroy, matching Terraform's own plan
summary line. The binary plan file and the raw `show -json` output are
deliberately NOT committed: both can embed resolved values (connection
strings, account-specific ARNs). The committed SHA-256 binds the safe
address-and-actions summary to the local binary that `make apply-plan PLAN=...`
applies after a second human confirmation.

## When artifacts are captured

Only during Arun-run apply windows, immediately before the apply, with real
AWS credentials on the machine that runs the apply. CI never runs
`terraform plan` (iac-ci is fmt/validate/tflint/checkov only, with no
credentials and no state access), so an empty stretch in this directory means
no apply window happened, not that the gate was skipped.
