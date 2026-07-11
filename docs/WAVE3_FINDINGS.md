# Wave 3 pressure-test findings (2026-07-11)

A loop-until-dry, 6-lens adversarial sweep (correctness, concurrency, security+tenancy, cost/FinOps, honesty/doc-drift, test-strength via mutation testing) over merged `master`, run after the Phase 5 merge (PR #4). 64 verification agents across 3 rounds; every finding was refute-first verified with a concrete reproduction before it counted. 31 findings survived verification. This ledger records each one and its disposition, so nothing is silently dropped.

Disposition key: **Fixed** (with a regression test, this wave) / **Documented** (a real limitation, war-storied and routed to the Codex production-hardening plan) / **Deferred** (real but lower-priority pre-existing robustness or test-strength, routed to Codex).

## Fixed this wave (with regression tests)

| # | Sev | File | Finding | Commit |
|---|-----|------|---------|--------|
| 22/23 | high | `infra/aws/harbormaster-permissions-boundary.json`, `modules/finops` | The boundary Allow-ceiling omitted `eks:*`/`kafka:*`/`autoscaling:*`, so once applied the EKS teardown guard and the finops MSK/ASG sweep would hit AccessDenied on their delete calls, report "nothing to tear down", and let ~$73/mo EKS + ~$18/day MSK bill past the $75 cap. Added the three services + a test pinning every teardown-critical service into the ceiling. | `d5718e6` |
| 2 | med | `serving/app/agents/gap_detector.py` | DRM prism-merge was single-pass seed clustering, not connected-components: a transitive overlap chain double-counted the middle prism and dropped the tail gap. Replaced with union-find + regression test. | `cb34053` |
| 18/19 | med/low | `mlops/route_optimizer/service.py`, `rollout.py` | The PPO stretch service trained on the default-weighted reward but read out the caller's weights (inconsistent), and used a fixed `total_steps=200` while `train_steps` could reach 500 (the cosine LR turns back up past `total_steps`). Threaded the weights into `train_optimizer` and set `total_steps=train_steps`. | this wave |
| 29/30/15 | med/low | `mlops/route_optimizer/{rollout,reward}.py` | Surviving mutants on the labeled stretch: greedy edge-selection direction, greedy visited-edge dedup, and `coverage_weight` scaling had no pinning test. Added three regression tests. | this wave |
| 6,7,8,13,14,24,25,26,27 | med/low | `README.md`, `docs/phases/PHASE_5.md`, `docs/AB_MASTERCLASS_AUDIT.md`, `docs/PLATFORM_BOOK.md`, `docs/EXPERIENCE_REPORT.md`, `docs/ARCHITECTURE.md`, `pyproject.toml` | Doc-drift after the Phase 5 merge: several docs still said Phase 5 "not built"; the war-story index and coverage/bench numbers were stale (including two errors introduced by this wave's own reconcile commit). All corrected against the tree. | `d5718e6` |

## Documented as known limitations (war-storied, routed to Codex hardening)

| # | Sev | File | Finding | Disposition |
|---|-----|------|---------|-------------|
| 1 | high | `cdc/schema/tenancy.py` | Under the co-tenancy model (two tenants, one Postgres), the tenant tables keep single-column business primary keys (`vessels.mmsi`, `watchlist.mmsi`, `sanctions_flags.id`). A tenant-B upsert of a key tenant A already holds conflicts with A's RLS-invisible row, raising 42501 -> unhandled HTTP 500, and the failure itself is a covert channel disclosing that another tenant holds the key. The tenant-private annotations (watchlist reason/severity, sanctions flags) need composite `(tenant_id, key)` keys. | War story P39. The fix is a real schema migration that ripples through the base DDL, the Debezium message-key mapper, and the registry upserts; routed to the Codex production-hardening plan rather than rushed. |
| 5 | high | `serving/app/watchlist.py`, `cdc/sinks/dynamo.py` | Phase 5 added `tenant_id`/RLS to the Postgres write side but not the CDC-maintained DynamoDB read side: the sink keys on MMSI+feature only, so two tenants' rows for the same MMSI collide (last-LSN-writer wins) and `WatchlistLookup.get` reads cross-tenant (its Redis key is also tenant-agnostic). Latent (needs the Phase 2 online store co-deployed multi-tenant, not yet run live). | War story P39 (same theme). The read path must carry the tenant dimension into the DynamoDB key + lookup + Redis key; routed to Codex. |
| 3 | med | `cdc/schema/tenancy.py` | The idempotent tenancy migration runs at backend connect with `app.tenant_id` already pinned, so a non-constant `DEFAULT` backfills pre-existing (single-tenant-era) rows with the migrating session's tenant, not the zero sentinel. | War story P39 (same theme); the backfill needs an explicit sentinel `UPDATE` before the column default takes over. Routed to Codex. |

## Deferred to the Codex production-hardening plan (real, lower-priority)

Pre-existing robustness (not Phase 5): **4** (`streaming/flink/job.py` `key_by` `json.loads` crashes the partitioning operator on a non-JSON record); **20** (`space_time_prism.py` `ellipse_polygon` center ignores the passed ellipse's own foci); **21** (`streaming/ingestor/ingest.py` Kinesis `PutRecords` partial-failure retry re-sends already-succeeded interior records); **11** (`watchlist.py` `... or 0.9` is a redundant no-op after `_attr`'s default); **12** (the stretch service trains inline in an `async def` handler, blocking the loop — acceptable for a demo stretch, noted).

Remaining test-strength (surviving mutants, new modules): **9/31** (`bedrock_explainer.py` forbidden-substring list + inclusive `score <= 1.0` bound untested); **10/16** (`disagreement_baseline.py` `>=` boundary + q95 nearest-rank off-by-one untested at some `k`); **17** (`tenant_drift.py` `sorted()` output order untested against an unsorted-insertion fixture); **28** (`ppo.py` clipped surrogate has no unit assertion, though the full gradient is numerically verified against finite differences in `test_route_optimizer_ppo` and by the Wave 2 review).

## Note: mutation testing on a shared tree

The sweep's mutation-testing lens edited source files in place (reverting after each). Two side effects surfaced and were handled: agents reverted their source edits cleanly (verified: `git status` showed no stray source diffs), but they left **stale `.pyc` bytecode** in `__pycache__` compiled from mutated source, which made `test_tenant_drift` fail against bytecode that no longer matched the (reverted) source. Cleared all `__pycache__`; the full suite is green. War story P40. Future mutation sweeps should run with `PYTHONDONTWRITEBYTECODE=1` or clear the cache on exit.
