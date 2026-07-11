# fde

Forward-deployed-engineer (FDE) artifacts for Harbormaster. Authored under Phase 5 gate 5.8 (`docs/phases/PHASE_5.md`), a writing gate, not a code gate.

> SIMULATED: every persona, customer, client name, and case study in this directory is fictional and built for demonstration only. None of it represents a real customer, and none of it is ESRI work, ESRI data, or an ESRI client. The single exception is `esri-uc-2023-requirements-memo.md`, which is real-grounded (themes Arun heard at the Esri User Conference), kept at architecture level with no client names and no restricted figures. See `docs/HONESTY.md` for the real-versus-simulated labeling rules.

## Index

| Document | Kind | Label |
| --- | --- | --- |
| [esri-uc-2023-requirements-memo.md](esri-uc-2023-requirements-memo.md) | Requirements memo from the Esri User Conference | REAL (architecture-level themes only) |
| [discovery-brief-port-authority.md](discovery-brief-port-authority.md) | Discovery-call brief, port authority persona | SIMULATED |
| [discovery-brief-marine-insurer.md](discovery-brief-marine-insurer.md) | Discovery-call brief, marine insurer persona | SIMULATED |
| [discovery-brief-coast-guard.md](discovery-brief-coast-guard.md) | Discovery-call brief, coast guard persona | SIMULATED |
| [user-research-synthesis.md](user-research-synthesis.md) | Research synthesis across the briefs and the memo | SIMULATED inputs, real method |
| [multi-tenant-client-in-the-loop-design.md](multi-tenant-client-in-the-loop-design.md) | Multi-tenant and client-in-the-loop design doc | REAL design doc; built-vs-design status marked per item |
| [sla-slo-tiers.md](sla-slo-tiers.md) | Service tiers, SLOs, and error budgets | DESIGN targets; live measurements deferred to the W4 window |
| [case-study-meridian-bay.md](case-study-meridian-bay.md) | Customer case study, end to end | SIMULATED |

## Ground rules these documents follow

- Every persona-shaped or customer-shaped document carries an explicit SIMULATED banner at the top, per `docs/HONESTY.md`.
- No document quotes a number that was not actually measured. Design targets are labeled design targets; deferred measurements are marked TBD-measured with the window they land in (W4).
- Every detector, flow, and platform capability referenced exists in this repository: the inline STAGD/TGARD/S-KBM agents, the corridor-deviation detector, the Pi-DPM async client, the Postgres HITL queue, and the CDC-fed watchlist/sanctions reasons. Nothing is described that was not built.
- Platform status claims match `docs/PLATFORM_BOOK.md`: Phases 0-4 built; Phase 5 in build; the W1 and W2 AWS showcases ran live; the Phase 2 MSK showcase has never run; the two-variant canary actuator is authored, not live-applied.
