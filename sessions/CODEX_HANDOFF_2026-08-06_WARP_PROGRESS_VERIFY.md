# Codex handoff: verify Warp progress since CODEX_HANDOFF_2026-08-09

Prepared at 2026-08-06T18:47:00Z after a Warp Agent session advanced the
Harbormaster project-remainder workflow from the Aug 9 canonical pause through
a sealed Recovery12 candidate-plan package and a pre-window human gate.

Read this file in full before taking any action.

This handoff does **not** replace `sessions/CODEX_HANDOFF_2026-08-09.md` for
safety law, Recovery8/10/11 history, or W4/Wave5 sequencing. It is the
**progress-verification and current-tip overlay**. Where this file and the Aug 9
handoff disagree on *current stage*, this file wins for stage and identities.
Where they disagree on *safety*, the stricter rule wins.

## 1. Status line

**Stage:** `CANDIDATE_PLAN_READY_FOR_HUMAN_GATE`

**Tip Warp checkpoint:**
`sessions/WARP_CHECKPOINT_20260806T184237Z.md`
SHA256 `372c9ddb80dbe9d165a059ebd5cfef825dd46cb4f7b2a7bbd6615f5a1e2f4929`

**Your job as Codex:** independently verify every claim below against the
filesystem and git. Do not trust narrative alone. Produce a verification report
with PASS/FAIL per check, then either (a) confirm the tip stage and stop at the
human gate, or (b) stop hard on the first failed identity/stop condition.

**Not your job:** run the Recovery12 helper, enter TOTP, capture a Terraform
plan, apply, mutate AWS, or "finish W4" in this session unless Arun explicitly
pastes a live command after window open.

## 2. Who is resuming and how to behave

- Model/harness: Codex (GPT-5.x-Sol or current Codex default).
- Repository: `/Users/arunsharma/code/harbormaster`
- Be thorough, adversarial, and honest-science. Prefer byte hashes over prose.
- No em dashes in any authored text.
- Commits only if Arun asks; author Arun Sharma; no AI co-author trailer.
- Preserve the intentionally dirty master worktree. Do not reset/clean/absorb
  unrelated untracked files.

## 3. Hard safety rails (unchanged, restate)

1. Never autonomously run real Terraform plan/apply/destroy/state mutation.
2. Never autonomously run AWS create/update/delete/modify/start/stop/invoke,
   ECR push, S3 upload, Kubernetes/Helm/Flink mutation, API retarget, signed
   live POST, or live load generation.
3. Never enter or request TOTP in chat. Arun enters TOTP only at a hidden
   terminal prompt.
4. Never send terminal input or an approval phrase on Arun's behalf.
5. Planning is not apply authority. Apply requires a separate package, separate
   human gate, and explicit continue after plan audit.
6. Never reuse expired, consumed, rejected, partial, or ambiguous helpers.
7. Recovery11 is permanently expired, unsealed, non-runnable, evidence only.
   Never invoke, extend epochs, complete its outer manifest, reseal, or rename
   it into Recovery12.
8. FinOps $75/mo cap and wet nightly teardown remain in force.
9. Numeric claims need executed evidence paths.

## 4. Bootstrap identities to re-verify first

These are the *original* Warp remainder bootstrap identities from the paste-in
prompt. They should still match on disk.

| Object | Expected SHA256 |
|--------|-----------------|
| `sessions/WARP_HANDOFF_2026-08-06_PROJECT_REMAINDER.md` | `110b5d3bc602c98bace4ea3061252951c9f58720aa341ad8c35b969c497b169e` |
| `sessions/CODEX_HANDOFF_2026-08-09.md` | `708637c60e250ae7bd3b0f6baff5afa657450579419ccc8db9b0d8046f07b00f` |
| `sessions/WARP_PROMPT_2026-08-06_PROJECT_REMAINDER.txt` | `050e1b447ea6201ed3841857effca894fbd25165df630bc0b10e172dbd4145ac` |

Also re-read in order:

1. `sessions/WARP_PROMPT_2026-08-06_PROJECT_REMAINDER.txt`
2. `sessions/WARP_HANDOFF_2026-08-06_PROJECT_REMAINDER.md`
3. `sessions/CODEX_HANDOFF_2026-08-09.md` (full, especially Section 17 + safety)
4. This file
5. Tip checkpoint `sessions/WARP_CHECKPOINT_20260806T184237Z.md`
6. `docs/runbooks/WAVE4_LIVE_WINDOWS.md` (skim for window law)

## 5. What changed since CODEX_HANDOFF_2026-08-09 (verify, do not redo blindly)

The Aug 9 handoff stopped with Recovery11 expired/unsealed and no live plan.
Warp remainder work since then claims the following. Treat each as a check.

### 5.1 Git

| Check | Expected |
|-------|----------|
| Package / operator pin | `9f585908082a8c6e705571ed7f7d546de1563eb5` (PR #44 merge; Recovery12 source pin) |
| Local `master` HEAD | Must be a descendant of the package pin. Likely a local docs-only commit that adds this verify handoff; do not require equality with the pin. |
| `origin/master` | `7468d5f61e02816ed7a4be3a8e3607998ee9f484` (PR #46 docs merge; may diverge from local master) |
| Dirty tree intentional | Modified `sessions/CODEX_HANDOFF_2026-07-12.md`; many untracked sessions/checkpoints and four `docs/plan-artifacts/2026-08-04-*.json` |
| Do not | merge origin into dirty master, reset, or delete untracked evidence |

PR #46 (docs-only, merged): branch commit
`77991008603d76a2b7c21f172a13aef6585554df`, merge
`7468d5f61e02816ed7a4be3a8e3607998ee9f484`.
Evidence ledger:
`artifacts/w4/20260806T174113Z-warp-project-remainder/`.
Docs paths claimed in that unit include
`docs/w4/EVIDENCE_INDEX.md`, `docs/w4/HONESTY_DELTA_RECOVERY12.md`,
`docs/w4/STATUS_RECOVERY12_PRE_CANDIDATE.md` plus older checkpoints committed on
that branch. Confirm those exist on `origin/master` if you inspect the remote
tree; local dirty master may not have checked them out.

### 5.2 Recovery11 (still dead)

Confirm still true:

- Package dir may exist as historical evidence under
  `artifacts/w4/20260805T214610Z-stage1-plan-recovery11` (or successor paths
  named in Aug 9 handoff).
- No active Recovery11 helper/harness process.
- No live invocation, no epoch extension, no rename-to-R12.

The original prompt's Recovery11 helper/harness/evidence hashes remain
historical bootstrap checks only. They are **not** the live package.

### 5.3 Recovery12 sealed package (live package, not yet run)

| Field | Expected |
|-------|----------|
| Directory | `artifacts/w4/20260806T160110Z-stage1-plan-recovery12` |
| Package id | `20260806T160110Z-stage1-plan-recovery12` |
| Plan label | `wave4-w4-eks-recovery-20260806T160110Z` |
| Helper | `operator-stage1-plan-recovery12.sh` |
| Helper SHA256 | `f6c6b4d19df1394dc1ed895e25c687edfc3c160fba36b4a195646890447ba515` |
| Outer manifest | `operator-plan-inputs.sha256` |
| Outer manifest SHA256 | `cfae7ee98193e4883a09d0db3520fe7d7caad802596b203c59598c30dc733d71` |
| Outer entry count | 17 |
| Outer self-check | `(cd package && shasum -a 256 -c operator-plan-inputs.sha256)` exit 0 |
| Pins file present | `recovery12-plan-pins.json` |
| Contract present | `plan-contract-recovery12.json` |
| Clean operator worktree | `/Users/arunsharma/code/harbormaster-r12-operator` at `9f585908082a8c6e705571ed7f7d546de1563eb5` |
| Helper executed | **false** |
| Apply authorized | **false** |
| Consumed/READY from live run | must be absent unless Arun already ran Phase 1 after this handoff |

Related pin SHAs recorded in earlier gate work (re-hash to confirm if present):

- pins content SHA (from prior gate): `adc986ea483a1f71282b8da0dcd608f9a8c40d6388f4535d7aa1d72821d9f83a`
- harness (prior gate): `18f7cc8cbaa983bd236695d0a10a7cc63f15c25c7701df310e547487d46da9eb`
- authorities (prior gate): `bc0d86232fd7cca6d16c52fb41f9fe54e4383e6e380cc83d16774ff10b02e753`
- contract (prior gate): `3ccf7ed44c2139fa5f5400466055874fbedac52c783af59bc873c1b0312c293b`

### 5.4 Human gate package (assembled, not executed)

| Field | Expected |
|-------|----------|
| Directory | `artifacts/w4/20260806T180258Z-warp-project-remainder/human-gate-candidate-plan/` |
| Doc | `HUMAN_GATE_CANDIDATE_PLAN.md` |
| Launch script | `ARUN_RUNS_candidate_plan.sh` SHA256 `48805d30d3cee90324197e75136ae334711e428191ecba4286071e90ca0adb4d` |
| gate-identities.json SHA256 | `94234607485f84bc71ee346d481242b873373271f3575dd3714dbad926a67ca7` |
| window_open_epoch | `1786122000` = 2026-08-07T17:00:00Z (10:00 PDT) |
| launch_cutoff_epoch | `1786125600` = 2026-08-07T18:00:00Z (11:00 PDT) |
| plan-ready | `1786127400` |
| apply-start (future only) | `1786129200` |
| absolute no-EKS | `1786132800` |
| operator_cidr | `174.62.118.133/32` |
| flink_verify_rc (pre-gate) | `0` |
| mismatches | `{}` |
| candidate_plan_authorized_to_run_now | `false` until clock >= open |

Work unit that built the gate:
`artifacts/w4/20260806T180258Z-warp-project-remainder/`
Owner UUID `9073fb73-dff1-4a88-a9a8-bd2d91408884`
Lock release receipt present; project-remainder lock should be **absent** now.

### 5.5 Warp checkpoint chain (newest tip first)

Verify each file exists and SHA256 matches. Stage for all tip entries is
`CANDIDATE_PLAN_READY_FOR_HUMAN_GATE` unless noted.

| Checkpoint | SHA256 | Stage / note |
|------------|--------|----------------|
| `WARP_CHECKPOINT_20260806T184237Z.md` | `372c9ddb80dbe9d165a059ebd5cfef825dd46cb4f7b2a7bbd6615f5a1e2f4929` | tip: session archive + terminal close |
| `WARP_CHECKPOINT_20260806T182930Z.md` | `9b0aab2b4257161c68d08135de998ee86f8c64a5121e8b6b564d3043c03fd150` | Phase 0 resume revalidation |
| `WARP_CHECKPOINT_20260806T181333Z.md` | `c6f2a8531e44f98fa40a35933ddf1bd9e76063eda82f7417c78be425739de756` | pre-window archive |
| `WARP_CHECKPOINT_20260806T180814Z.md` | `f2e97b6f629839ec4d931000e89e567cbdadc4406625c79429f202fe642df0a6` | pre-gate local revalidation complete |
| `WARP_CHECKPOINT_20260806T175755Z.md` | `42c518f4b9f3f5a53964716dfbe39d131ab72f9ab1697d48fd8c4e913d4a5d76` | prior |
| `WARP_CHECKPOINT_20260806T173554Z.md` | `c47a02fbef30163d67ee084f0257319bf2e6c3de26c74382e254af57fede04bc` | prior / docs lane |
| `WARP_CHECKPOINT_20260806T172546Z.md` | `d9273912d32f13955464b7fda7f27365af825abfb5c3ffec3f82c1aa663a6cf2` | prior |
| `WARP_CHECKPOINT_20260806T170832Z.md` | `cc955209d925fa37e048bd451b9e703ec6f0f94e6bccb710dd5cdd871e7d1677` | `LOCAL_WORK_IN_PROGRESS` (historical) |
| `WARP_CHECKPOINT_20260806T155756Z.md` | `d49b1715afc4758bdc7ac5e8001fbca8e60b5887d59a345e0b18d5115b9d6cba` | `READ_ONLY_RECONCILIATION_COMPLETE` |
| `WARP_CHECKPOINT_20260806T150223Z.md` | `ff16848f6e3ac567eba3d67debecf8c59ce1d875fd9f825788ffd92e33c2caac` | `READ_ONLY_RECONCILIATION_READY_FOR_HUMAN_AUTH` |

Predecessor links inside each checkpoint must form a chain without broken
hashes. Spot-check tip -> 182930 -> 181333 -> 180814.

### 5.6 Important result directories

| Path | Role |
|------|------|
| `artifacts/w4/20260806T160110Z-stage1-plan-recovery12` | sealed R12 package |
| `artifacts/w4/20260806T180258Z-warp-project-remainder` | pre-gate revalidation + human gate |
| `artifacts/w4/20260806T182930Z-warp-project-remainder` | Phase 0 resume verify |
| `artifacts/w4/20260806T184237Z-session-archive-close` | session archive + tmux close log |
| `artifacts/w4/20260806T174113Z-warp-project-remainder` | PR #46 docs merge evidence |
| `artifacts/w4/phase1-window-watch` | local macOS window notifier |

### 5.7 Phase 1 watcher (local only)

| Field | Expected at handoff write |
|-------|---------------------------|
| Dir | `artifacts/w4/phase1-window-watch` |
| PID file | `watcher.pid` (was `38239`) |
| Alive | `kill -0 $(cat watcher.pid)` succeeds **or** document dead and do not claim notify |
| State | `waiting_for_open` until epoch open |
| helper_auto_run | `false` |
| On open | writes `WINDOW_OPEN.notify` + macOS notification |
| Does not | run helper, TOTP, terraform |

If the laptop slept across the window, watcher may have missed the fire. Clock
and gate script remain authoritative.

### 5.8 Terminals / locks

| Check | Expected |
|-------|----------|
| Project-remainder lock | **absent** (`artifacts/w4/.warp-project-remainder.lock`) |
| tmux `hm-recovery4` | killed earlier (Recovery4 zombie) |
| tmux `hm-w4` and session `0` | killed during archive close |
| Recovery4 package | historical failed RO only; do not rerun |

### 5.9 Recovery4 note (context only)

Older tmux Recovery4 died after a wet sweep on a local false-positive
`jq -S`+`cmp` state compare (line 761). No mutation. Comparator fix merged as
PR #43 historically. Recovery4 is consumed evidence, not a live path.

## 6. Exact verification procedure for Codex (run this)

Work only in read-only mode unless Arun orders otherwise.

```bash
set -euo pipefail
cd /Users/arunsharma/code/harbormaster

# A. Bootstrap hashes
test "$(shasum -a 256 sessions/WARP_HANDOFF_2026-08-06_PROJECT_REMAINDER.md | awk '{print $1}')" = "110b5d3bc602c98bace4ea3061252951c9f58720aa341ad8c35b969c497b169e"
test "$(shasum -a 256 sessions/CODEX_HANDOFF_2026-08-09.md | awk '{print $1}')" = "708637c60e250ae7bd3b0f6baff5afa657450579419ccc8db9b0d8046f07b00f"
test "$(shasum -a 256 sessions/WARP_PROMPT_2026-08-06_PROJECT_REMAINDER.txt | awk '{print $1}')" = "050e1b447ea6201ed3841857effca894fbd25165df630bc0b10e172dbd4145ac"

# B. Git pins
# Package/operator pin remains PR #44. Local master may also carry this verify-handoff commit.
PIN=9f585908082a8c6e705571ed7f7d546de1563eb5
test "$(git -C /Users/arunsharma/code/harbormaster-r12-operator rev-parse HEAD)" = "$PIN"
git merge-base --is-ancestor "$PIN" HEAD
HEAD_NOW=$(git rev-parse HEAD)
echo "HEAD=$HEAD_NOW pin=$PIN"
# Confirm this handoff file is present on HEAD or as a tracked path
git cat-file -e HEAD:sessions/CODEX_HANDOFF_2026-08-06_WARP_PROGRESS_VERIFY.md
# origin may be docs-ahead and diverged:
git rev-parse origin/master
# expect 7468d5f61e02816ed7a4be3a8e3607998ee9f484 unless remote moved again

# C. Recovery12 outer
PKG=artifacts/w4/20260806T160110Z-stage1-plan-recovery12
test "$(shasum -a 256 $PKG/operator-stage1-plan-recovery12.sh | awk '{print $1}')" = "f6c6b4d19df1394dc1ed895e25c687edfc3c160fba36b4a195646890447ba515"
test "$(shasum -a 256 $PKG/operator-plan-inputs.sha256 | awk '{print $1}')" = "cfae7ee98193e4883a09d0db3520fe7d7caad802596b203c59598c30dc733d71"
(cd $PKG && shasum -a 256 -c operator-plan-inputs.sha256)

# D. Operator worktree already checked in B against PIN

# E. Tip checkpoint
test "$(shasum -a 256 sessions/WARP_CHECKPOINT_20260806T184237Z.md | awk '{print $1}')" = "372c9ddb80dbe9d165a059ebd5cfef825dd46cb4f7b2a7bbd6615f5a1e2f4929"

# F. Gate cmd
GATE=artifacts/w4/20260806T180258Z-warp-project-remainder/human-gate-candidate-plan
test "$(shasum -a 256 $GATE/ARUN_RUNS_candidate_plan.sh | awk '{print $1}')" = "48805d30d3cee90324197e75136ae334711e428191ecba4286071e90ca0adb4d"
test "$(shasum -a 256 $GATE/gate-identities.json | awk '{print $1}')" = "94234607485f84bc71ee346d481242b873373271f3575dd3714dbad926a67ca7"

# G. Lock absent
test ! -e artifacts/w4/.warp-project-remainder.lock

# H. Clock vs window (do not run helper)
python3 - <<'PY'
import time
open_e, cut_e = 1786122000, 1786125600
now = int(time.time())
print("now", now, "open_ok", now >= open_e, "before_cut", now < cut_e)
print("hours_to_open", round((open_e-now)/3600, 2))
PY

# I. No Recovery12 helper process
pgrep -lf 'operator-stage1-plan-recovery12|ARUN_RUNS_candidate_plan' || true

# J. Watcher (informational)
if [ -f artifacts/w4/phase1-window-watch/watcher.pid ]; then
  pid=$(cat artifacts/w4/phase1-window-watch/watcher.pid)
  kill -0 "$pid" && echo watcher_alive=$pid || echo watcher_dead
  cat artifacts/w4/phase1-window-watch/status.json
fi
```

Then write a short report:

1. PASS/FAIL table for A-J
2. Confirmed stage
3. Any drift (especially if `origin/master` moved past `7468d5f`, watcher dead,
   or unexpected READY/consumed markers appeared)
4. Explicit statement: helper not run by verifier

If any sealed identity fails: **STOP**. Do not repair sealed Recovery12 bytes in
place. Open a new investigation unit.

## 7. What Warp claims it did NOT do (must remain true)

- No Recovery12 helper execution
- No TOTP
- No Terraform plan binary / apply
- No AWS mutation beyond any earlier documented R0 identity probe in pre-gate
  notes (direct `arun-admin`; platform role not assumed for that probe)
- No apply package prepared
- No W4 complete claim

If you find a `.tfplan`, READY success marker, or consumed marker under the R12
package that post-dates this handoff and Arun did not run Phase 1, treat as
incident and stop.

## 8. Human gate still required (Phase 1)

Only Arun, only after open and before launch cutoff:

```bash
bash /Users/arunsharma/code/harbormaster/artifacts/w4/20260806T180258Z-warp-project-remainder/human-gate-candidate-plan/ARUN_RUNS_candidate_plan.sh
```

Or the equivalent block embedded in
`sessions/WARP_CHECKPOINT_20260806T184237Z.md`.

Expected success fragments include:

- `RECOVERY12_CANDIDATE_PLAN_PASSED_THE_PRELIMINARY_GATE_AND_SEALED_BEFORE_CUTOFF`
- package consumed; no apply; `apply_authority=false`
- post-capture validation pending

After that terminal state: new work unit for **immutable plan audit only**.
Do not prepare apply until audit green and Arun explicitly continues.

## 9. If window already open or already closed when you start

- **Open and before cutoff, helper not run:** tell Arun the gate command is
  live; do not run it yourself.
- **Past launch cutoff, helper not run:** Recovery12 live path is non-runnable
  for that window. Keep package as evidence. Next is Recovery13+ fresh package
  from new RO evidence. Do not extend R12 epochs in place.
- **Helper already run:** switch to plan-audit mode on immutable artifacts;
  still no apply without separate gate.

## 10. Suggested first move

1. Run Section 6 verification script.
2. Read tip checkpoint + gate doc.
3. Reply with an ~15 line verification summary: stage, PASS/FAIL counts, hours
   to open/cutoff, watcher alive?, origin drift, next human action.
4. Stop at human gate unless Arun orders a scoped local-only task that cannot
   touch sealed R12 bytes.

## 11. Honesty spine

- Sealed package ready is not plan captured.
- Plan captured is not apply authorized.
- Docs PR #46 on origin does not move the operator worktree pin.
- Operator/package pin staying on `9f58590` while origin is `7468d5f` and local
  master may also have the verify-handoff commit is expected posture, not a cue
  to merge origin into the dirty tree.
- Watcher notification is convenience only; epoch checks in the launch block
  are authoritative.

## 12. Files Codex should not rewrite

- Any sealed file under `artifacts/w4/20260806T160110Z-stage1-plan-recovery12/`
- Already-hashed `sessions/WARP_CHECKPOINT_*.md` (create successors only)
- `sessions/CODEX_HANDOFF_2026-08-09.md` bootstrap bytes
- Unrelated dirty/untracked evidence files listed in git status

End of handoff.
