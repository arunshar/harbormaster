# Discovery-call brief: Northlake Marine Mutual

> SIMULATED: this organization, persona, and every name and detail in this document is fictional, written to demonstrate discovery-call preparation. It is not a real customer, prospect, or engagement, and it is not ESRI work, ESRI data, or an ESRI client. See `docs/HONESTY.md`.

## Persona snapshot

- Organization: Northlake Marine Mutual (fictional), a mid-market hull and machinery underwriter with a protection-and-indemnity book concentrated in coastal bulk carriers.
- Contact: Priya Raman (fictional), Head of Claims Analytics. Owns fraud triage and the data inputs to underwriting reviews. Reports to the Chief Underwriting Officer.
- Trigger for the call: a disputed total-loss claim where the vessel's AIS record showed a multi-hour gap immediately before the reported casualty, and the claims team had no tooling to characterize whether the gap was ordinary for that route.

## Hypotheses going in

- Claims analysts pull AIS history vendor by vendor, per claim, by hand; there is no baseline of what normal reporting behavior looks like for a route or vessel class.
- Their latency need is near-real-time to batch: a claim review runs on days, renewal analytics on quarters. Nobody needs seconds.
- Evidence quality matters more than detection speed: anything they use has to survive an opposing expert's scrutiny.
- They will not accept a black-box score in a claims file.

## Discovery questions

Opening and context:

1. Take the last claim where AIS behavior mattered. What did the analyst actually do, step by step, and how long did it take?
2. How many claims a year turn on vessel-movement evidence?

Problem and workflow:

3. When a gap shows up in a track, how do you decide today whether it is suspicious or just a satellite coverage hole?
4. What would a defensible written explanation of a flagged track need to contain for it to enter a claims file?
5. Who reviews and signs off on a movement-analysis finding before it affects a claim decision?

Data and integration:

6. Which AIS and vessel-registry vendors do you already buy, and would a platform need to ingest those feeds or can public-archive data carry the analysis?
7. Do you keep an internal list of vessels or owners under heightened scrutiny, and how is it maintained?

Success, security, procurement:

8. If this worked, does the win show up as faster claim cycle time, fewer leakage dollars, or better renewal pricing?
9. What are your data-handling requirements for claims material, and can analysis run in a shared environment or must it be isolated?
10. Who owns the budget: claims, underwriting, or IT?

## What Harbormaster can show today, mapped to their likely needs

| Their need | Harbormaster capability | Status |
| --- | --- | --- |
| Characterize whether a gap is abnormal for the track | STAGD-lineage abnormal-gap detection with a space-time-prism feasibility envelope | Built, inline |
| Rule out physically impossible reported movement | S-KBM kinematic gate; `implausible_speed` reason with evidence | Built |
| Detect possible rendezvous during a dark period | TGARD / DC-TGARD rendezvous detection across gaps | Built, inline |
| Route-conformance context for a casualty position | Corridor-deviation detector against a NOAA-chart-derived graph | Built; live-verified in W1 |
| Scrutiny list drives automatic flags | Watchlist/sanctions registry with CDC-fed online reads | Built; local-stack accepted, AWS MSK showcase not yet run |
| Explanations an expert can defend | Typed reason codes with per-reason evidence; Phase 5 adds a narrative layer that only restates the deterministic reasons and never changes a score | Reasons built; narrative layer in build |
| Historical baselining at book scale | Iceberg lake with Athena queries over replayed public archives (~600 GB historical AIS scale) | Built; EMR backfill live-verified in W2 |
| Isolated processing for claims data | Postgres row-level security per tenant, default-deny | Phase 5 design, in build |

## Honest gaps to disclose if asked

- Harbormaster is a personal demonstration platform built on public AIS data; it has never processed an insurer's claims data.
- The learned model head serves a labeled demo stand-in; the defensible outputs today are the deterministic detectors and their evidence, which is arguably what a claims file wants anyway.
- Batch-tier SLOs (the tier this buyer needs) are design targets, not measured commitments; measurements land in the W4 window.

## Red flags and disqualifiers

- If they need court-admissible chain of custody over licensed commercial AIS feeds, that is a data-vendor and legal question Harbormaster does not answer.
- If the ask collapses to "score every renewal automatically with no human review," that conflicts with the platform's human-in-the-loop posture and deserves a direct no.

## Proposed next step

A worked example on public archive data: one synthetic claim scenario, the gap and rendezvous analysis run end to end, and the written reason-code evidence shown in the form a claims file would consume.
