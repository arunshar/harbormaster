# User-research synthesis: maritime anomaly monitoring buyers

> SIMULATED INPUTS, REAL METHOD: the three discovery interviews synthesized here are the fictional personas in this directory (`discovery-brief-port-authority.md`, `discovery-brief-marine-insurer.md`, `discovery-brief-coast-guard.md`), not real conversations. The fourth source, the Esri UC requirements memo, is real-grounded at architecture level. This document demonstrates the synthesis method on that mixed corpus; its conclusions validate the method, not market demand. See `docs/HONESTY.md`.

## Method

Standard four-step interview synthesis, applied exactly as it would be to real transcripts:

1. Source normalization. Each brief's hypotheses, questions, and disclosed gaps were treated as the interview record. The UC memo's seven themes entered as a fourth source with a "real, architecture-level" provenance tag.
2. Open coding. Every need-shaped statement was tagged with a short code (EXPLAIN, ISOLATE, LATENCY-SPLIT, GAP-AS-SIGNAL, LIST-DRIVEN, TRIAGE-LOAD, INTEGRATE, EVIDENCE-GRADE, COST).
3. Affinity grouping. Codes clustered into themes; each theme records which sources support it, so a theme carried by one persona cannot masquerade as consensus.
4. Prioritization. Themes ranked by breadth (how many sources) then by consequence (whether the source framed it as a gate to adoption or a nice-to-have).

## Theme table

| # | Theme | Sources | Gate or nice-to-have | Platform mapping |
| --- | --- | --- | --- | --- |
| 1 | Flags must carry inspectable reasons and evidence; a bare score is ignored or inadmissible | Port, Insurer, Coast Guard, UC memo (4/4) | Gate | Typed reason codes with evidence dicts, noisy-OR fusion (built); Bedrock narrative layer (Phase 5, in build) |
| 2 | Tenant isolation and data sovereignty are procurement gates, not features | Port, Insurer, Coast Guard, UC memo (4/4) | Gate | RLS default-deny per `tenant_id`, per-tenant model variants (Phase 5 design, in build) |
| 3 | AIS gaps are the signal of interest, with a feasibility bound on where the vessel could have gone | Port, Insurer, Coast Guard, UC memo (4/4) | Gate for coast guard; strong for others | STAGD-lineage gap detection, space-time prism, TGARD rendezvous (built, inline) |
| 4 | Latency needs split by mission into at least a live tier and a batch tier | Port, Coast Guard, UC memo (3/4); Insurer is batch-only, which itself confirms the split | Gate for live missions | Three-tier SLO design (design targets; W4 measurement window) |
| 5 | Customer-maintained interest lists must drive flags, with fast propagation | Port, Insurer, Coast Guard (3/4) | Gate | Watchlist/sanctions registry, CDC to online store (built; AWS MSK showcase not run) |
| 6 | Alert-volume discipline decides adoption; reviewers abandon noisy systems | Port, Coast Guard (2/4) | Gate | HITL queue plus human verdicts feeding the Phase 4 flywheel; per-tenant drift monitoring so one tenant's shift does not degrade another's alert quality (Phase 5, in build) |
| 7 | Findings must land in existing tools, not a new pane of glass | Port, UC memo (2/4) | Nice-to-have short term, gate at scale | Open gap; Iceberg/Athena is queryable, but no push integration exists |
| 8 | Evidence must survive adversarial scrutiny (opposing expert, prosecutor) | Insurer, Coast Guard (2/4) | Gate for those missions | Deterministic detectors with per-reason evidence help; chain-of-custody over licensed feeds is out of scope |
| 9 | Cost must be predictable under bursty load | UC memo, implicit in Port (2/4) | Nice-to-have | Scale-to-zero surfaces, budget guardrails (built); EKS teardown guard (Phase 5, in build) |

## What the synthesis changes

- Theme 1 and Theme 2 being unanimous is the strongest argument that Phase 5's two headline items (the explanation layer and RLS multi-tenancy) are sequenced correctly: they are the two most common gates.
- Theme 6 justifies per-tenant drift monitoring in user terms, not just engineering terms: alert quality is per-tenant trust, and a global drift average hides exactly the shift that erodes one tenant's trust.
- Theme 7 is the clearest genuinely missing capability: no persona asked for the HITL console as their end state. Any real engagement would start with an integration conversation.
- Theme 8 suggests the deterministic-detectors-first posture is a selling point for evidence-grade missions, not a limitation to apologize for.

## Limitations, stated plainly

- Three of four sources are fictional and were written by the same author who built the platform; confirmation bias is structural, not incidental. The themes are hypotheses to test in real discovery, nothing more.
- The one real source (the UC memo) is reconstructed from memory at architecture level, three years after the fact.
- No pricing, willingness-to-pay, or competitive signal exists in this corpus, and none is claimed.
