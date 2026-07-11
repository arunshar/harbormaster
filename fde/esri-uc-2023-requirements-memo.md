# Requirements memo: themes heard at the Esri User Conference (July 2023)

Status: REAL-GROUNDED. This is the one document in `fde/` that is not simulated. It records requirement themes Arun Sharma heard in sessions, expo-floor conversations, and hallway discussions at the Esri User Conference in San Diego during the Summer 2023 internship period.

Provenance and boundaries, per `docs/HONESTY.md`:

- Architecture-level themes only. No client names, no named organizations, no internal Esri project names, no restricted figures, and no Esri-private datasets or diagrams appear here or anywhere in Harbormaster.
- Reconstructed in July 2026 from memory of the 2023 conference. These are paraphrased themes, not quotes, and no line is attributed to any person or organization. Arun is the source of record; anything he does not remember hearing should be struck.
- The internship deliverable work itself is Esri's and is not described here beyond what `docs/HONESTY.md` already permits. This memo is about what the maritime GIS user community was asking for, which is public-conversation material, not employer work product.

## Why this memo exists

Harbormaster's later phases (multi-tenancy, explanations, SLO tiers, the FDE artifact set) are not requirements invented in a vacuum. The themes below are the market signal that shaped them. Each theme maps to what Harbormaster actually built, with the build status stated honestly.

## Theme 1: a bare anomaly score is not actionable

The most consistent thread across maritime-analytics conversations: operations staff do not act on an unexplained score. They want to see why a vessel was flagged, tied to evidence they can inspect (the gap window, the corridor segment departed, the list that matched).

Harbormaster response: the scoring service returns typed reason codes (`implausible_speed`, `abnormal_gap`, `off_corridor`, `unexpected_node`, `watchlist_hit`, `sanctions_hit`), each with a severity and an evidence dict, fused by noisy-OR into the score. Built (Phase 1-2). The Phase 5 Bedrock layer narrates those already-computed reasons and never alters a score; in build.

## Theme 2: humans stay in the loop, and the loop needs an audit trail

Agencies and commercial operators alike described review workflows: an analyst confirms or rejects a flag before anyone acts, and the decision has to be recorded and defensible later.

Harbormaster response: a Postgres-backed HITL queue with a Streamlit review console and a feedback endpoint; reviewer verdicts persist and later feed the Phase 4 retraining flywheel. Built (Phases 1 and 4).

## Theme 3: organizations will not share a data plane

Port authorities, insurers, and government users each assume their vessel interest lists and review decisions are theirs alone. Several conversations treated tenant isolation and data residency as procurement gate questions, not features.

Harbormaster response: Phase 5's multi-tenant design, Postgres row-level security with default-deny (`tenant_id` required, fail-closed at the database), per-tenant SageMaker production variants, per-tenant SLO and drift monitoring. Design record DR-7 existed from the start; the implementation is Phase 5, in build.

## Theme 4: latency expectations split cleanly by mission

A live watchfloor wants seconds. Compliance and claims workflows are content with hours or a daily batch. Users framed these as different products with different price points, not one SLA.

Harbormaster response: the three-tier SLO design (real-time, near-real-time, batch) in `fde/sla-slo-tiers.md`, wrapping the existing burn-rate machinery. Design targets stated; live measurements deferred to the W4 window.

## Theme 5: AIS gaps are events, not missing data

Practitioners repeatedly described transponder dark periods as the signal of interest ("going dark" near a boundary or rendezvous point), not a data-quality nuisance to interpolate away.

Harbormaster response: this is the platform's core thesis. Gap detection (STAGD lineage) and rendezvous detection across gaps (TGARD lineage) run as first-class inline detectors, with the space-time prism as the feasibility envelope. Built (Phase 1).

## Theme 6: outputs must land in existing tools

Nobody asked for a new pane of glass. Flags and evidence need to arrive where analysts already work: their GIS, their dashboards, their ticketing.

Harbormaster response: partially addressed. Every event lands in Iceberg and is queryable via Athena; the HITL console is a demo surface, not an integration story. A real deployment would push findings into the customer's tooling. Open, stated plainly.

## Theme 7: cost has to be predictable under bursty load

AIS volume is bursty; budgets are fixed. Users wanted scale-up under load without a standing bill during quiet periods.

Harbormaster response: scale-to-zero everywhere it exists (Fargate, SageMaker async, EMR Serverless), a $30 soft / $75 hard budget pair with a breach-triggered IAM deny, and Phase 5's KEDA scale-to-zero plus a structural EKS teardown guard. Built through Phase 4; the EKS half is in build.
