#!/usr/bin/env bash
# Gate 3.4: the one-way MSI -> S3 checkpoint export. Arun-run, from the Mac
# (~/code/harbormaster), after scp'ing a finished Pi-DPM checkpoint down from
# MSI (the harbormaster repo/venv is Mac-only; MSI's own Miniforge env trains
# the checkpoint but does not host this package). This script never pulls
# anything back down: it is the one-way door by construction, matching
# mlops/manifest.py's public API (no resume/pull entry point exists there).
#
# Usage:
#   scripts/export_checkpoint.sh \
#     --checkpoint /path/to/local/checkpoint.pt \
#     --region <aws-region> \
#     --run-id <msi-slurm-job-id-or-run-name> \
#     --step <int> \
#     --git-sha <sha> \
#     --config-hash <sha256-of-the-training-config> \
#     --data-fingerprint <sha256-from-lake/export_training_set.py> \
#     --mirror-version <mirror-synthetic-anomaly-version-tag> \
#     --wandb-run-id <wandb-run-id> \
#     --s3-uri s3://<models-bucket>/pidpm/<region>/<run-id>/
#
# Requires: AWS credentials for the harbormaster account/region (same
# guardrails as everywhere else in this repo: this script only ever
# aws s3 sync's UP; it never applies Terraform and never deletes anything).

set -euo pipefail

usage() {
  echo "usage: $0 --checkpoint PATH --region REGION --run-id ID --step N \\" >&2
  echo "          --git-sha SHA --config-hash HASH --data-fingerprint FP \\" >&2
  echo "          --mirror-version VER --wandb-run-id ID --s3-uri s3://..." >&2
  exit 1
}

CHECKPOINT="" REGION="" RUN_ID="" STEP="" GIT_SHA="" CONFIG_HASH=""
DATA_FINGERPRINT="" MIRROR_VERSION="" WANDB_RUN_ID="" S3_URI=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --checkpoint) CHECKPOINT="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --step) STEP="$2"; shift 2 ;;
    --git-sha) GIT_SHA="$2"; shift 2 ;;
    --config-hash) CONFIG_HASH="$2"; shift 2 ;;
    --data-fingerprint) DATA_FINGERPRINT="$2"; shift 2 ;;
    --mirror-version) MIRROR_VERSION="$2"; shift 2 ;;
    --wandb-run-id) WANDB_RUN_ID="$2"; shift 2 ;;
    --s3-uri) S3_URI="$2"; shift 2 ;;
    *) usage ;;
  esac
done

for v in CHECKPOINT REGION RUN_ID STEP GIT_SHA CONFIG_HASH DATA_FINGERPRINT MIRROR_VERSION WANDB_RUN_ID S3_URI; do
  if [[ -z "${!v}" ]]; then
    echo "missing required --${v,,}" >&2
    usage
  fi
done

if [[ ! -f "$CHECKPOINT" ]]; then
  echo "checkpoint not found: $CHECKPOINT (scp it down from MSI first)" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT

REPO_ROOT="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" - "$STAGE_DIR" "$CHECKPOINT" "$STEP" \
  "$GIT_SHA" "$CONFIG_HASH" "$DATA_FINGERPRINT" "$MIRROR_VERSION" "$WANDB_RUN_ID" <<'PYEOF'
import os
import sys
from pathlib import Path

# stdin has no real __file__, so the repo root comes from the env var bash set,
# not from Path(__file__): that would resolve to something meaningless here.
sys.path.insert(0, os.environ["REPO_ROOT"])
from mlops.manifest import save

stage_dir, checkpoint, step, git_sha, config_hash, data_fingerprint, mirror_version, wandb_run_id = sys.argv[1:9]

entry = save(
    Path(stage_dir),
    int(step),
    Path(checkpoint).read_bytes(),
    meta={
        "git_sha": git_sha,
        "config_hash": config_hash,
        "data_fingerprint": data_fingerprint,
        "mirror_synthetic_anomaly_version": mirror_version,
        "wandb_run_id": wandb_run_id,
    },
)
print(f"staged manifest entry: step={entry.step} sha={entry.sha} path={entry.path}")
PYEOF

echo "==> aws s3 sync (one-way, up only) --region $REGION $STAGE_DIR -> $S3_URI"
aws s3 sync --region "$REGION" "$STAGE_DIR" "$S3_URI"
echo "done: $S3_URI now carries this checkpoint's manifest entry"
