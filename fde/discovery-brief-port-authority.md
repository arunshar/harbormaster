# Discovery-call brief: Meridian Bay Port Authority

> SIMULATED: this organization, persona, and every name and detail in this document is fictional, written to demonstrate discovery-call preparation. It is not a real customer, prospect, or engagement, and it is not ESRI work, ESRI data, or an ESRI client. See `docs/HONESTY.md`.

## Persona snapshot

- Organization: Meridian Bay Port Authority (fictional), a mid-size container and bulk port with a single approach corridor, two anchorages, and a vessel traffic service (VTS) watchfloor staffed around the clock.
- Contact: Dana Okafor (fictional), Director of Marine Operations. Owns VTS staffing, incident response, and berth scheduling. Reports to the harbor master.
- Trigger for the call: two recent near-miss incidents involving vessels that deviated from the approach corridor while their AIS reporting was intermittent.

## Hypotheses going in

- The watchfloor sees raw AIS on a chart display but has no automated flagging; deviations are caught by whoever happens to be looking.
- Dark periods (AIS gaps) near the anchorage are common and mostly benign, so any gap alerting they tried before drowned the watchfloor in noise.
- They care about seconds-to-minutes latency for the corridor, but their monthly compliance reporting is a batch job someone assembles by hand.
- Procurement will ask where the data lives and who else can see it.

## Discovery questions

Opening and context:

1. Walk me through the last deviation incident. Who noticed it, how long after it started, and what happened next?
2. How many vessels transit the approach corridor on a typical day, and how many operators watch the display at once?

Problem and workflow:

3. When a vessel goes dark near the anchorage today, what happens? Is a gap ever the thing that triggers a closer look, or only a nuisance?
4. If a system flagged a vessel right now, who would act on it, and what evidence would they need on screen to trust the flag?
5. What does a false alarm cost you, and how many per shift before the watchfloor starts ignoring the system?

Data and integration:

6. What chart and traffic tooling does the watchfloor run today, and does a new flag need to appear inside it or is a separate review queue acceptable?
7. Do you maintain your own vessel interest list, and who updates it?

Success, security, procurement:

8. Six months in, what number or story tells you this worked?
9. Where must your data be processed and stored, and does any other organization share the platform?
10. Who besides you has to say yes?

## What Harbormaster can show today, mapped to their likely needs

| Their need | Harbormaster capability | Status |
| --- | --- | --- |
| Corridor deviation flagged automatically | Corridor-deviation detector (`off_corridor`, `unexpected_node`) against a NOAA-chart-derived corridor graph | Built; ran live end to end in the W1 showcase |
| Gaps treated as signal, not noise | STAGD-lineage abnormal-gap detection with a space-time-prism feasibility envelope | Built, inline in the scoring path |
| Physically impossible tracks screened out | S-KBM kinematic gate plus the cheap physical-plausibility gate in the stream job | Built |
| Analyst review with an audit trail | Postgres-backed HITL queue, Streamlit console, persisted verdicts | Built |
| Their own interest list drives flags | Watchlist/sanctions registry, CDC-fed online store, `watchlist_hit`/`sanctions_hit` reasons | Built; CDC accepted on the local stack, AWS MSK showcase not yet run |
| Their data isolated from other tenants | Postgres row-level security, default-deny per `tenant_id` | Phase 5 design, in build; not yet demonstrable |
| Watchfloor latency guarantees | Three-tier SLO design (real-time tier) | Design targets only; cold-start and latency measurements land in the W4 window |

## Honest gaps to disclose if asked

- Harbormaster is a personal demonstration platform, not a product with deployments behind it.
- The learned second-opinion model head (Pi-DPM, async) currently serves a labeled demo stand-in checkpoint, not a trained model; the deterministic detectors are the load-bearing scoring path.
- Flag delivery into their existing VTS display is an integration story that does not exist yet; today the review surface is the HITL console.

## Red flags and disqualifiers

- If they need flags rendered inside a certified VTS system with type approval, this is out of scope.
- If they expect a contractual SLA on day one, the SLO tiers are design targets, not commitments.

## Proposed next step

A replay demonstration against public AIS data for a corridor comparable to theirs: planted deviation and gap events, flags reaching the review queue, reviewer labeling shown end to end. Zero customer data required.
