# Multi-tenant and client-in-the-loop design

Status: REAL design document for Phase 5 (`docs/phases/PHASE_5.md`, gates 5.4-5.6). Phases 0-4 are built; Phase 5 is in build on branch `phase5-multitenant`. Every item below carries a built / in-build / design marker, and nothing here claims a live-verified capability that has not run. Decision-record grounding: DR-7 (multi-tenant isolation as a bulkhead) in `docs/SYSTEM_DESIGN_DECISIONS.md`.

## The two ideas

1. Multi-tenant: several client organizations share the platform's planes while the database, the model variants, the SLOs, and the drift monitors treat each tenant as its own bulkhead. Isolation is enforced by infrastructure, default-deny, never by an application-layer check someone has to remember.
2. Client-in-the-loop: the client's own reviewers are the human half of the loop. Their HITL verdicts are first-class data: they close the loop on alert quality, drive the concept-drift proxy, and (with consent) feed the preference-data flywheel that retrains the learned head.

## Isolation layers, inside out

### Database: Postgres row-level security (in build, gate 5.4)

Every table gains `tenant_id uuid NOT NULL`, RLS enabled, and a policy of the shape `USING (tenant_id = current_setting('app.tenant_id')::uuid)`. The failure posture is the design's core: a session that never sets `app.tenant_id` reads zero rows. There is no code path where forgetting the tenant context returns everyone's data; the database itself is the enforcement point. `Settings.tenant_id = ""` preserves single-tenant back-compat, matching the platform's established empty-string-disables convention. The acceptance drill (gate 5.9, M-tenant-leak) attempts a cross-tenant read and requires Postgres, not the application, to block it.

### Model serving: per-tenant SageMaker production variants (design, gate 5.4/5.3-adjacent)

The Pi-DPM async endpoint gains one production variant per demoed tenant instead of a shared variant, so one tenant's traffic and model quality are isolated at the AWS resource level. Honest caveats: the endpoint currently serves a labeled demo stand-in checkpoint, never a trained model, and the per-endpoint variant ceiling is an implementation-time check, per the phase doc's own sprint-honest scope note.

### SLOs: per-tenant tiers over the existing burn-rate machinery (in build, gate 5.4)

The Google SRE multi-window burn-rate calculator already exists and is mutation-tested (`serving/app/burn_rate.py`; 14.4x over 1h/5m and 6x over 6h/30m page, 3x over 24h/2h tickets). Phase 5 adds only the per-tenant dimension: a `PerTenantSlo` layer over the existing `Slo`/`evaluate` shapes, three tier tables (real-time, near-real-time, batch; see `fde/sla-slo-tiers.md`), and a per-tenant `series_provider` fed to the existing `make_burn_check`. One tenant's burn can trigger a revert while another tenant's identical window does not. The calculator is never rebuilt.

### Drift: per-tenant partitioning of the existing detector (in build, gate 5.5)

`mlops/drift.py` (PSI/KS, Phase 4) is called once per tenant partition via a thin wrapper. The reason is a user-trust argument, not a code aesthetic: a single tenant's population shift gets averaged below the alert threshold in a pooled check, and that tenant then experiences quietly degrading alert quality nobody can see. The acceptance fixture requires the per-tenant check to alert while a same-fixture global baseline does not.

### Blast radius around it all

The tenancy bulkhead sits inside the platform's existing containment: an IAM permissions boundary and resource-scoped role management (authored, not applied), API Gateway SigV4 default authorization with throttling (authored, not applied), and the $30/$75 budget pair with a breach-triggered deny (live since Phase 0).

## The client in the loop

### Review: the tenant's own analysts work the queue (built; per-tenant scoping in build)

The HITL queue is Postgres-backed with persisted verdicts (Phase 1); under RLS each tenant's reviewers see exactly their own queue. Every flagged item carries the full typed reason set (`implausible_speed`, `abnormal_gap`, `off_corridor`, `unexpected_node`, `watchlist_hit`, `sanctions_hit`) with per-reason evidence, so the reviewer judges evidence, not a bare score.

### Explanation: narrative for the reviewer, never a second opinion (in build, gate 5.6)

The Bedrock explainer receives only the already-computed reason codes and the score, never raw trajectory data, and its output populates a narrative field only; the score and reasons are never overwritten. Fail-open: a Bedrock outage leaves the narrative empty and the queue flowing. A unit gate asserts the prompt can never contain a raw position fix.

### Feedback: verdicts as data (built, Phase 4)

Reviewer agreement and disagreement feed two built mechanisms: the concept-drift proxy (a rising reviewer-disagreement rate, cross-validated against near-threshold trace volume, with the alert threshold derived from an accumulated baseline) and the preference-triple builder for DPO/GRPO retraining, with ambiguous rows dropped and a hard-violation flag on every triple. Per-tenant consent and data-use boundaries for the flywheel are a deployment-contract question flagged here, not silently assumed.

### Client-visible operations

Each tenant's SLO tier, burn status, and drift results are per-tenant artifacts by construction, so client reporting falls out of the same partitioning rather than a separate reporting pipeline.

## What this design deliberately does not do

- No tenant self-service management surface: 2-3 demo tenants, provisioned by configuration, per the phase scope guard.
- No cross-tenant analytics of any kind, even aggregated; nothing in the schema supports reading across tenants once RLS is on.
- No consensus protocol and no sharded query router, per `docs/HONESTY.md`; tenancy shards nothing, it partitions rows and variants inside managed services.
- No claim of live verification yet: the RLS drill, the per-tenant burn revert, and the drift contrast all become claims only when gate 5.9's drills run.
