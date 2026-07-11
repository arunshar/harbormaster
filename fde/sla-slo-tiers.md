# Service tiers, SLOs, and error budgets

Status: DESIGN. The three tiers below are the gate 5.4 design (`docs/phases/PHASE_5.md`), stated as targets, not commitments and not measurements. Harbormaster is a personal demonstration platform; nothing here is a contractual SLA. Every number is labeled measured, design target, or TBD-measured. Live Phase 5 measurements (cold start, front-door latency under multi-tenant load) are explicitly deferred to the W4 demo window and appear only as TBD-measured placeholders until then.

## What is actually measured today

| Quantity | Value | Provenance |
| --- | --- | --- |
| Score-kernel p95, single event, golden path | ~0.58-0.61 ms | Local benchmark on an Apple M4 Pro dev machine (`bench/SCORE_BENCH.md`); a local figure, not a cloud figure |
| Score-kernel throughput | ~1,760-1,787 scores/sec/core | Same local benchmark, same caveat |
| Phase 1 end-to-end (replay to HITL) | Passed the Phase 1 targets live | Gate G8 ran live 2026-07-04 (W1); the planted anomaly reached the HITL queue within the Phase 1 SLO set |
| SageMaker async wake from zero instances | ~30 seconds to InService | One live observation, W2 window, 2026-07-04 |

Nothing else in this document is a measurement.

## The existing single-tenant SLO set (built, Phase 1)

`serving/app/slo.py` holds the Phase 1 targets and a pure evaluator (a missing measurement breaches, never passes silently):

| SLI | Target | Direction |
| --- | --- | --- |
| score_success_ratio | 0.999 | at least |
| score_kernel_p95_ms | 300 ms | at most |
| replay_to_hitl_p95_s | 10 s | at most |

## Burn-rate policy (built, wired to promotion)

The Google SRE multi-window multi-burn-rate calculator (`serving/app/burn_rate.py`, tested and mutation-tested):

| Tier | Burn threshold | Long / short window | Action |
| --- | --- | --- | --- |
| Fast | 14.4x | 1 h / 5 m | Page; auto-rollback signal |
| Slow | 6x | 6 h / 30 m | Page; auto-rollback signal |
| Ticket | 3x | 24 h / 2 h | Ticket, no rollback |

A page-severity fire feeds `should_rollback`, consumed by the promotion pipeline through `make_burn_check`. Phase 5 wires this per tenant (a tenant-partitioned series provider and a tier-supplied target); the calculator itself is unchanged.

## The three tenant tiers (gate 5.4 DESIGN targets)

These are design targets for the per-tenant `PerTenantSlo` layer. None has been measured; the W4 window is where measurement happens. Monthly error budgets are arithmetic on a 30-day month, not observations.

| SLI | Real-time tier | Near-real-time tier | Batch tier |
| --- | --- | --- | --- |
| Intended mission | Live watchfloor cueing | Case building, claims triage | Historical baselining, reporting |
| Score success ratio | 99.9% (budget 43.2 min/mo) | 99.5% (budget 3.6 h/mo) | 99.0% (budget 7.2 h/mo) |
| Flag latency, event to HITL queue, p95 | 10 s | 5 min | 24 h (batch completion) |
| Score-kernel p95 | 300 ms | 1 s | not applicable (offline) |
| Watchlist change to live effect | 5 s | 5 min | next batch run |
| Burn-rate wiring | Full page tiers, auto-rollback armed | Page tiers, rollback armed | Ticket tier only |

Design rationale in one line per tier: the real-time tier inherits the Phase 1 targets unchanged, so the already-exercised single-tenant numbers become the strictest tier rather than inventing new ones; the near-real-time tier relaxes latency two orders of magnitude for review-driven missions; the batch tier trades latency for completeness and cost.

## TBD-measured placeholders (W4 window)

These get numbers only when measured live; writing an estimate here would be fabrication.

| Quantity | Status |
| --- | --- |
| KEDA 0 to 1 cold start, EKS serving pod, first request served | TBD-measured (gate 5.3 / drill M3, the phase's explicit "measured, not estimated" acceptance criterion) |
| Front-door p95 under concurrent multi-tenant load | TBD-measured (W4) |
| Backpressure episode: time to engage, watermark lag, time to drain | TBD-measured (drill M3 postmortem) |
| Whether the cold start breaches the real-time tier (war story P7 grounds only if it does) | TBD-measured (W4) |
| Per-tenant burn-rate revert exercised against a live endpoint | TBD-run (gate 5.9) |

## Honesty rails on this document

- Design target means chosen goal, stated before measurement; it is falsifiable by the W4 window and will be revised in this file, not quietly met by definition.
- The cold-start row exists because scale-to-zero is the platform's cost posture, and the honest cost of that posture is a cold start whose size is currently unknown. It stays unknown here until measured.
- If any tier target proves unreachable when measured, the correction lands here as a dated edit, per the platform's no-silent-revision discipline.
