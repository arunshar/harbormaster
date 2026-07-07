# Harbormaster session handoff - 2026-07-04 (sprint closeout: W1/W2 live, Phase 5 signed off, Blocks E/F)

## One-line state

Phases 0, 1, and 3 are live-AWS-verified and Phase 3 is torn down clean; Phase 2 remains local-stack-only (its AWS MSK showcase has not run); Phase 4 is code-complete on `phase4-flywheel`, rebased onto `phase3-lake`'s current HEAD and mergeable as the full linear chain (`master -> phase1-serving-slice -> phase2-cdc -> phase3-lake -> phase4-flywheel`); Phase 5 is authored, fact-checked, and signed off as a plan-only doc (build is a later sprint). Two real external-audit gaps (HM3-AUDIT-01, HM3-AUDIT-02) and one internally-found reward-hacking-probe gap are all fixed and verified. `phase4-flywheel` is ahead of `origin/phase4-flywheel` by 14 commits; `phase3-lake` is ahead of `origin/phase3-lake` by 18 commits. Nothing is pushed yet (push and PR creation are Arun-run, handed off below).

## W1: Phase 1 first-ever live AWS run

Real anomaly reached the HITL queue end to end (Kinesis -> Flink -> gate -> DynamoDB -> scorer -> HITL), confirmed with MMSI 367000003 (`off_corridor`, score 1.0). Five real bugs found and fixed live, all in `PLATFORM_WAR_STORIES.md` P13-P16 plus the DynamoDB/schema findings:
- PyFlink's Python UDF worker subprocess can't resolve local packages by reference (cloudpickle by-value vs by-reference); fixed by inlining `flink/transforms.py`'s logic into `job.py`'s `__main__`.
- `boto3` missing in the same worker; fixed via `env.set_python_requirements()`.
- DynamoDB `put_item` rejects native `float`; fixed via a `Decimal` round-trip.
- Replay-fixture timestamps made every item's TTL already-expired on arrival; fixed via wall-clock TTL at the write site.
- `score_request()`'s payload didn't match the real `AisScoreIn` schema, silently 422ing every call; fixed to send `{mmsi, fix, history}`.
- Gate G8's target MMSI never flagged because the planner's `n_history >= 3` gate was never met (Flink tracked only 1 prior fix); fixed via a rolling `HISTORY_WINDOW = 5`.

## W2: Phase 3 AWS showcase, run live and torn down

EMR Serverless backfill and the SageMaker demo-standin endpoint + promotion pipeline both ran live and GREEN, after eight more real bugs (P17-P24, P26): EMR IAM missing read on its own `code/` prefix; a `mapInPandas` schema mismatch; pyiceberg's Glue catalog needing explicit region properties; `zip(strict=)` incompatible with EMR's real Python 3.9; a Docker OCI-vs-v2-manifest mismatch for SageMaker's `CreateModel`; a missing container `ENTRYPOINT`; a shared-working-directory branch mixup (no real damage); an async-API-vs-sync-promotion-loop timing collision. An external audit (`~/code/sagemaker-deepdive`) caught HM3-AUDIT-01 (scale-in dimension bug, ~$530/mo exposure) before this was ever applied; fixed and verified live (P25). Verifying the other half then surfaced a second, distinct dimension bug in the scale-out-from-zero alarm; fixed and verified live end to end, 0-to-1 wake in about 30s (P26). The real promotion pipeline ran against the live endpoint end to end, `final_status="promoted"` matching the pinned `clean_run` sequence exactly.

**Part 3 teardown, run and verified:** `make plan` showed a clean `0 add / 0 change / 13 destroy` scoped exactly to `module.emr_backfill` and `module.sagemaker_pidpm`; `make apply` completed with zero errors; post-apply confirmed via `aws sagemaker list-endpoints` and `aws emr-serverless list-applications` that nothing Phase-3-specific remains. Phase 0/1 outputs unaffected.

## Phase 5: authored and signed off (build deferred)

`docs/phases/PHASE_5.md` (9 gates, M0-M9: EKS/KEDA front-door migration, multi-tenant `tenant_id` isolation via Postgres RLS, per-tenant SLO burn-rate, Bedrock explanation layer, a labeled PPO stretch service) was authored after a 4-agent research pass fact-checked every reuse anchor against real files (not the master plan's prose). Real gaps surfaced and folded in: DR-13's burn-rate mechanism was never actually implemented anywhere in the repo (`serving/app/slo.py` is static-threshold only); KEDA/ArgoCD exist nowhere as working config in `pcrf-monorepo`, only as aspirational comments; the EKS control plane doesn't scale to zero (~$73/mo flat), so the doc adds a new structural (EventBridge + Lambda force-destroy) teardown guard beyond what the master plan originally specified. Signed off by Arun 2026-07-04. Build is explicitly a later sprint.

## Two parallel sessions reconciled

A deep-dive into two other in-flight sessions ("Harbormaster Phase 2 CDC pipeline," "Databricks material review") found they were the same `~/code/harbormaster` repo (not separate efforts) and the source of the external audit (`sagemaker-deepdive`), respectively. Real findings folded in, both signed off and fixed:

- **Reward-hacking-probe magnitude-blind gap.** A 4-lens adversarial review of `phase4-flywheel` found a "boundary-riding" candidate could smuggle severe safety violations past the probe's rate-only comparison. Fixed: `blocked = mean_up and (rate_up or candidate_mean_hard < baseline_mean_hard)`, no new fields/thresholds. Predicted blast radius held exactly (`test_custom_hard_violation_threshold_is_respected` correctly flipped); the strict xfail now genuinely passes, marker removed.
- **HM3-AUDIT-02.** No Model Package Group creation path existed anywhere, so a real registry-based promotion would have failed. Fixed: `aws_sagemaker_model_package_group.pidpm` added to `modules/sagemaker_pidpm` (a Terraform resource, not a manual runbook step, so it tears down with the module). Gate 3.6's isolated plan count moves 9 -> 10 to add, verified.

## phase4-flywheel rebased onto phase3-lake

11 commits replayed cleanly onto `phase3-lake`'s current HEAD (the W1 Flink fixes, the Phase 5 doc, the HM3-AUDIT-02 fix). Two mechanical conflicts, both resolved:
- `PLATFORM_WAR_STORIES.md`: renumbered this phase's P13/P14 (drift-proxy, reward-hacking) to P27/P28, the next available numbers after `phase3-lake`'s own P13-P26 (not P19/P20 as `docs/WRITEUP_PLAN.md` had guessed before P17-P26 existed).
- `.gitignore`: kept both branches' additions (Maven build output + `mlops/preference_data/`).

Full suite 376 passed / 9 skipped, ruff clean, `terraform validate` clean, committed-values plan zero-diff, all re-verified post-rebase. `phase4-flywheel` is the full linear chain and mergeable via a single PR.

## Block E: portfolio + honesty updates

- `~/.claude/skills/temporal-interview-prep/references/supabase-multigres-cover-note.md`: already accurate (only describes the CDC mechanism, never claims an AWS showcase ran); verified, no change needed.
- Resume Harbormaster bullet sharpened across 4 variants (`AWS_PACE_resume.md`, `AWS_PACE_resume_1page.md`, `AWS_GenAI_resume.md`, `Google_General_resume.md` in `~/code/career-narratives`, committed `1ebb2dd`): now names Kinesis/Flink, the SageMaker scale-to-zero + promotion pipeline, the EMR data-quality gate, and CDC, all with only committed-artifact-backed claims.
- `docs/HONESTY.md` gained a new dated section noting the Phase 1/3 live showcases moved the MLOps claim from designed to actually-run, while stating plainly the endpoint served a labeled demo stand-in and Phase 2's AWS showcase has not run.
- `README.md`'s phase-status table and repository-layout table refreshed; several "(later phase)" labels on `streaming/`, `cdc/`, `serving/` were false (all built and live-run) and are now corrected.

## Open items for Arun (not acted on by this session)

- **Push and PR** (git push is Arun-run only): see the exact commands below.
- `docs/WRITEUP_PLAN.md` (untracked, a 4-document writing initiative by Fable, referencing Phase 5 only as "planned," with a now-stale verified-facts section) needs a sequencing call: is it a subset of Block E's remaining scope, a separate later initiative, or superseded? Not touched.
- Delete the demo ECR repo (`hm-pidpm-demo`) if not reusing it for a future demo; low priority, not done.
- The remaining 17 HM3-AUDIT hardening/decision-record/no-change findings (async failure-path visibility, invocation timeout/InferenceId, the self-paired shadow stand-in, Inference Recommender right-sizing, others) are documented in `docs/phases/PHASE_3.md`'s new addendum, not acted on.
- The Terraform-plan-output-artifact gap (no committed `.tfplan`/fixture backing the numeric plan-count claims) and `infra/lambda/` being excluded from CI ruff are both documented, pre-existing, non-blocking.

## Push and PR handoff (git push is Arun-run only)

```
cd ~/code/harbormaster
git push origin phase3-lake
git push origin phase4-flywheel
gh pr create --base master --head phase4-flywheel \
  --title "Harbormaster: Phases 0-4 (guardrails through the drift/HITL/RL flywheel)" \
  --body-file <(echo "See docs/phases/PHASE_1.md through PHASE_4.md, docs/HONESTY.md, PLATFORM_WAR_STORIES.md P1-P28, and this session's handoff (sessions/SESSION_HANDOFF_2026-07-04_sprint_closeout.md) for full detail.")
```

`~/code/career-narratives` (`main`, commit `1ebb2dd`) is a separate repo/push, at Arun's discretion.
