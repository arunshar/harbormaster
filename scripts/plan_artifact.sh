#!/usr/bin/env bash
# Capture a reviewable Terraform plan artifact for the envs/base root.
#
# Closes the known no-committed-plan-artifact gap (see
# docs/plan-artifacts/README.md): every Arun-run apply window starts with this
# script so the exact planned resource changes are recorded in-repo before
# anything is applied. The binary plan file and the raw `show -json` output
# stay local (both can embed sensitive resolved values); only the
# address+actions summary is written to docs/plan-artifacts/.
#
# Usage:
#   scripts/plan_artifact.sh <label>    # e.g. scripts/plan_artifact.sh phase4-flywheel
#
# Writes docs/plan-artifacts/<UTC-date>-<label>.json:
#   {generated_utc, label, add, change, destroy,
#    resource_changes: [{address, actions}]}
# and echoes the add/change/destroy counts. A replace counts as both an add
# and a destroy, matching Terraform's own "X to add ... Y to destroy" summary.
#
# Requires: AWS credentials (plan reads real state through the S3 backend) and
# jq or python3 for the summary step. Arun-run only, same as every apply in
# this repo; CI never runs terraform plan.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$REPO_ROOT/infra/terraform/envs/base"
OUT_DIR="$REPO_ROOT/docs/plan-artifacts"

usage() {
  echo "usage: $0 <label>   (label: [A-Za-z0-9._-]+, e.g. phase4-flywheel)" >&2
  exit 2
}

[ "$#" -eq 1 ] || usage
label="$1"
case "$label" in
  "" | *[!A-Za-z0-9._-]*) usage ;;
esac

plan_tmp="$(mktemp -t hm-plan.XXXXXX)"
json_tmp="$(mktemp -t hm-plan-json.XXXXXX)"
trap 'rm -f "$plan_tmp" "$json_tmp"' EXIT

terraform -chdir="$TF_DIR" plan -input=false -out="$plan_tmp"
terraform -chdir="$TF_DIR" show -json "$plan_tmp" > "$json_tmp"

mkdir -p "$OUT_DIR"
artifact="$OUT_DIR/$(date -u +%Y-%m-%d)-${label}.json"
generated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if command -v jq >/dev/null 2>&1; then
  jq --arg generated "$generated" --arg label "$label" '
    [.resource_changes[]? | {address, actions: .change.actions}] as $rc
    | {
        generated_utc: $generated,
        label: $label,
        add: ([$rc[] | select(.actions | index("create"))] | length),
        change: ([$rc[] | select(.actions | index("update"))] | length),
        destroy: ([$rc[] | select(.actions | index("delete"))] | length),
        resource_changes: $rc
      }
  ' "$json_tmp" > "$artifact"
else
  HM_GENERATED="$generated" HM_LABEL="$label" HM_ARTIFACT="$artifact" \
    python3 - "$json_tmp" <<'PY'
import json
import os
import sys

with open(sys.argv[1]) as f:
    plan = json.load(f)
rc = [
    {"address": c["address"], "actions": c["change"]["actions"]}
    for c in plan.get("resource_changes") or []
]
summary = {
    "generated_utc": os.environ["HM_GENERATED"],
    "label": os.environ["HM_LABEL"],
    "add": sum(1 for c in rc if "create" in c["actions"]),
    "change": sum(1 for c in rc if "update" in c["actions"]),
    "destroy": sum(1 for c in rc if "delete" in c["actions"]),
    "resource_changes": rc,
}
with open(os.environ["HM_ARTIFACT"], "w") as f:
    json.dump(summary, f, indent=2)
    f.write("\n")
PY
fi

counts="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["add"], d["change"], d["destroy"])
' "$artifact")"
read -r add change destroy <<< "$counts"

echo "plan artifact: $artifact"
echo "plan summary: $add to add, $change to change, $destroy to destroy"
