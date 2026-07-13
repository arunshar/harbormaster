# Wave 3 pressure-test findings (2026-07-11)

A loop-until-dry, 6-lens adversarial sweep (correctness, concurrency, security+tenancy, cost/FinOps, honesty/doc-drift, test-strength via mutation testing) over merged `master`, run after the Phase 5 merge (PR #4). 64 verification agents across 3 rounds. The sweep originally recorded 31 findings as verified; a later targeted audit refuted finding 21, leaving 30 verified findings. This ledger preserves that correction so nothing is silently dropped.

Disposition key: **Fixed** (with a regression test) / **Deferred** (real but lower-priority pre-existing robustness or test-strength, routed to Codex) / **Refuted** (the recorded production defect did not exist; the ledger and test gap were corrected).

## Fixed this wave (with regression tests)

| # | Sev | File | Finding | Commit |
|---|-----|------|---------|--------|
| 22/23 | high | `infra/aws/harbormaster-permissions-boundary.json`, `modules/finops` | The boundary Allow-ceiling omitted `eks:*`/`kafka:*`/`autoscaling:*`, so once applied the EKS teardown guard and the finops MSK/ASG sweep would hit AccessDenied on their delete calls, report "nothing to tear down", and let ~$73/mo EKS + ~$18/day MSK bill past the $75 cap. Added the three services + a test pinning every teardown-critical service into the ceiling. | `d5718e6` |
| 2 | med | `serving/app/agents/gap_detector.py` | DRM prism-merge was single-pass seed clustering, not connected-components: a transitive overlap chain double-counted the middle prism and dropped the tail gap. Replaced with union-find + regression test. | `cb34053` |
| 18/19 | med/low | `mlops/route_optimizer/service.py`, `rollout.py` | The PPO stretch service trained on the default-weighted reward but read out the caller's weights (inconsistent), and used a fixed `total_steps=200` while `train_steps` could reach 500 (the cosine LR turns back up past `total_steps`). Threaded the weights into `train_optimizer` and set `total_steps=train_steps`. | this wave |
| 29/30/15 | med/low | `mlops/route_optimizer/{rollout,reward}.py` | Surviving mutants on the labeled stretch: greedy edge-selection direction, greedy visited-edge dedup, and `coverage_weight` scaling had no pinning test. Added three regression tests. | this wave |
| 6,7,8,13,14,24,25,26,27 | med/low | `README.md`, `docs/phases/PHASE_5.md`, `docs/AB_MASTERCLASS_AUDIT.md`, `docs/PLATFORM_BOOK.md`, `docs/EXPERIENCE_REPORT.md`, `docs/ARCHITECTURE.md`, `pyproject.toml` | Doc-drift after the Phase 5 merge: several docs still said Phase 5 "not built"; the war-story index and coverage/bench numbers were stale (including two errors introduced by this wave's own reconcile commit). All corrected against the tree. | `d5718e6` |

## Fixed during subsequent local production hardening

| # | Sev | File | Finding | Fix and local evidence |
|---|-----|------|---------|------------------------|
| 1 | high | `cdc/schema/tenancy.py`, `serving/app/registry.py`, `serving/app/hitl.py`, `scripts/migrate_p39.py` | Under the co-tenancy model, single-column business primary keys made a same-key tenant-B upsert conflict with tenant A's RLS-invisible row. | Added composite `(tenant_id, business_key)` primary keys and conflict targets plus an explicit, transactional migration. A real local PostgreSQL 16 run verified two tenants can hold the same MMSI while RLS keeps their rows isolated. |
| 5 | high | `serving/app/watchlist.py`, `cdc/consumer/envelope.py`, `cdc/sinks/dynamo.py`, `cdc/sinks/redis_cache.py` | The CDC-maintained DynamoDB and Redis read side used tenant-oblivious MMSI keys, so same-MMSI rows could overwrite or read across tenants. | Carried `tenant_id` through Debezium envelopes, feature entity IDs, DynamoDB partitions, Redis keys, and `WatchlistLookup`. A fresh local kind stack passed the CDC smoke in 4.28 seconds and all five Phase 2 e2e criteria; a local production-image run verified same-MMSI isolation across both API containers. |
| 3 | med | `cdc/schema/tenancy.py`, `scripts/migrate_p39.py` | Backend-connect DDL could backfill pre-existing rows from the session tenant instead of the zero sentinel. | Replaced implicit migration with an explicit sentinel backfill and row-preserving census. The migration shares an advisory lock with runtime schema bootstrap, rejects active CDC, and requires an all-tenant `BYPASSRLS` or superuser view when RLS is already enabled. |
| 4 | n/a | `streaming/flink/job.py`, `streaming/flink/transforms.py`, `streaming/flink/window_logic.py` | The production `key_by` selector parsed JSON inline, so malformed input could fail the partitioning operator before the process function reached its quarantine path. | Replaced the throwing selector with strict `mmsi_partition_key` copies in source and packaged runtime code. Invalid inputs use sentinel key `-1`; `FeatureProcess` calls `_quarantine` and returns before keyed-state access. Local tests cover valid, malformed, out-of-range, and deeply nested JSON. |
| 20 | n/a | `serving/app/components/space_time_prism.py` | `mobr` and `ellipse_polygon` centered a supplied ellipse on the prism's anchor pair instead of the supplied ellipse's own foci. | Within the kernel's documented local projection domain, centered each active ellipse on its own foci with its own projection. Direct geometry, dynamic-merge, and meter-scale-at-latitude regressions cover the fix. The module is now a maintained GeoTrace-derived fork. |
| 9/31 | n/a | `serving/app/bedrock_explainer.py`, `serving/tests/test_bedrock_explainer.py` | The forbidden-vocabulary list and inclusive score endpoints had surviving test mutations. | Pinned every forbidden token independently and both score endpoints. Removing `coordinate` and making the upper bound exclusive now produces two focused-test failures. |
| 10/16 | n/a | `mlops/disagreement_baseline.py`, `mlops/tests/test_disagreement_baseline.py` | The inclusive usable-window boundary and nearest-rank q95 index had surviving test mutations. | Pinned `n=20` inclusion and the `k=19` and `k=20` q95 boundaries. Changing `>=` to `>` fails `n=20`; lowering the ceil offset by one fails `k=19`; raising it by one fails `k=20`. |
| 17 | n/a | `mlops/tenant_drift.py`, `mlops/tests/test_tenant_drift.py` | Deterministic tenant ordering had no reverse-insertion regression for either the per-tenant result map or drifted-tenant fan-out. | Pinned both order contracts with reverse-insertion fixtures. Removing either `sorted()` call independently fails its focused regression. |
| 28 | n/a | `mlops/route_optimizer/ppo.py`, `mlops/tests/test_route_optimizer_ppo.py` | The scalar clipped surrogate had no direct value assertion across both advantage signs and both sides of the ratio clip interval. | Pinned four hand-computed cases. Replacing `minimum` with `maximum` fails all four. The earlier finite-difference claim was inaccurate and is removed; this regression proves the scalar surrogate value. |

The fixes and evidence for findings 1, 3, and 5 are local only. The live AWS Postgres migration and
tenant-qualified DynamoDB/Redis rebuild remain a human-run maintenance window;
neither was executed during this hardening change. See
`docs/drills/P39_test_suite.md`, `docs/drills/P39_local_cdc_smoke.md`, and
`docs/runbooks/P39_COMPOSITE_KEY_MIGRATION.md`.

Finding 4 was verified only through local source tests and the packaged Flink
artifact. No AWS command or Managed Service for Apache Flink job was run, so
this does not establish live throughput, backpressure, or quarantine behavior.
Malformed records do not read or update keyed state, but they share sentinel
key `-1`. A sustained malformed-input burst can therefore concentrate work in
one key group and create a hot partition. See
`docs/drills/FLINK_MMSI_KEY_LOCAL_2026-07-13.md`.

## Deferred to the Codex production-hardening plan (real, lower-priority)

Pre-existing robustness (not Phase 5): **11** (`watchlist.py` `... or 0.9` is a redundant no-op after `_attr`'s default); **12** (the stretch service trains inline in an `async def` handler, blocking the loop; acceptable for a demo stretch, noted).

Pre-existing projection debt: the local equirectangular prism kernel does not
split antimeridian-crossing geometry and is unstable near the poles. Finding 20
fixes supplied-ellipse centering within the documented local projection domain;
it does not close those broader geographic edge cases.

## Refuted during production hardening

**21** (`streaming/ingestor/ingest.py`) was a false positive. The production putter has mapped every `PutRecords` response against the current pending list since commit `5cb5a01`, so later retry rounds do not re-send records that already succeeded. The real issue was test strength: the two-call regression never exercised a failure after the pending list shrank. A three-round noncontiguous regression now pins `[0,1,2,3,4,5,6] -> [1,4,6] -> [1,6]`. A mutation that maps the second response against the original batch fails that regression. No production retry-mapping defect was fixed.

No ordered test-strength findings remain.

## Note: mutation testing on a shared tree

The sweep's mutation-testing lens edited source files in place (reverting after each). Two side effects surfaced and were handled: agents reverted their source edits cleanly (verified: `git status` showed no stray source diffs), but they left **stale `.pyc` bytecode** in `__pycache__` compiled from mutated source, which made `test_tenant_drift` fail against bytecode that no longer matched the (reverted) source. Cleared all `__pycache__`; the full suite is green. War story P40. Future mutation sweeps should run with `PYTHONDONTWRITEBYTECODE=1` or clear the cache on exit.
