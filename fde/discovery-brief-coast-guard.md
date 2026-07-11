# Discovery-call brief: Valdoria Coast Guard, Maritime Domain Awareness Directorate

> SIMULATED: this organization, persona, and every name and detail in this document is fictional, written to demonstrate discovery-call preparation. It is not a real customer, prospect, or engagement, and it is not ESRI work, ESRI data, or an ESRI client. No real nation or agency is depicted. See `docs/HONESTY.md`.

## Persona snapshot

- Organization: the Coast Guard of Valdoria (fictional), a coastal state with a large exclusive economic zone, chronic illegal-fishing pressure, and a small patrol fleet that cannot be everywhere.
- Contact: Commander Luis Ferreira (fictional), Chief of Maritime Domain Awareness. Owns the common operating picture and tasking recommendations to the patrol squadron.
- Trigger for the call: repeated pattern of fishing vessels disabling AIS at the EEZ boundary, transshipping at sea, and re-appearing with track histories that look clean at a glance.

## Hypotheses going in

- Their watch center fuses AIS with occasional patrol and aerial sightings; the AIS picture is the always-on layer and the one they can automate against.
- Dark-vessel behavior is their top signal: gaps, loitering pairs, and boundary-hugging tracks.
- They need both a live tier (cue a patrol now) and a batch tier (build cases over months).
- Sovereignty constraints are hard requirements: national data stays national, and any shared platform needs provable isolation.
- Alert volume discipline decides adoption; a watch officer who sees ten bad flags stops reading the eleventh.

## Discovery questions

Opening and context:

1. Describe the last interdiction that worked. What cued it, how old was the cue when the patrol launched, and what would have made it faster?
2. How many vessels are inside your EEZ picture at a given moment, and how many watch officers triage it?

Problem and workflow:

3. When a vessel goes dark at the boundary today, what does the watch center actually do with that fact?
4. For a transshipment case, what evidence do prosecutors need, and how much of it is movement-derived?
5. Who is allowed to see and act on a flag: the watch center only, or district commands too?

Data and integration:

6. Which AIS sources feed your picture today (terrestrial, satellite, national coastal network), and where does that data legally have to live?
7. Do you maintain vessel-of-interest and sanctions lists nationally, and how fast must a list change take effect in the live picture?

Success, security, procurement:

8. A year from now, is success measured in interdictions, in deterrence (fewer dark events), or in prosecutions that hold up?
9. What accreditation does a system need before it touches your operational picture?
10. Is procurement national, or through a regional fisheries body with shared funding?

## What Harbormaster can show today, mapped to their likely needs

| Their need | Harbormaster capability | Status |
| --- | --- | --- |
| Dark-period detection with a feasibility envelope | STAGD-lineage abnormal-gap detection; space-time prism bounds where the vessel could have gone | Built, inline |
| Transshipment / rendezvous inference across gaps | TGARD and DC-TGARD rendezvous detection between vessel pairs | Built, inline |
| Impossible-track screening (spoofing-shaped input) | S-KBM kinematic gate plus the cheap physical-plausibility gate upstream | Built |
| Lane and boundary conformance | Corridor-deviation detector on a NOAA-chart-derived graph (`off_corridor`, `unexpected_node`) | Built; live-verified in W1 |
| National interest lists drive the picture | Watchlist/sanctions registry, CDC to the online store, sub-5-second flag-to-scored target | Built; local-stack accepted, AWS MSK showcase not yet run |
| Watch-officer triage with case history | HITL queue with persisted reviewer verdicts | Built |
| Live tier plus case-building batch tier | Three-tier SLO design over the existing burn-rate machinery | Design targets; measurements land in the W4 window |
| Provable isolation from any other tenant | Postgres row-level security, default-deny, enforced by the database, not application code | Phase 5 design, in build |

## Honest gaps to disclose if asked

- Harbormaster is a personal demonstration platform on public data. It has never held government data and is not accredited for it.
- The learned model head serves a labeled demo stand-in checkpoint; deterministic detectors carry the scoring today.
- Multi-region and sovereign-hosting postures do not exist: the platform is single-region by declared design (ADR 0003), and that would be a real deployment conversation, not a toggle.
- The platform deliberately implements no consensus protocol and no sharded query router; coordination relies on managed services, stated per `docs/HONESTY.md`.

## Red flags and disqualifiers

- Any request to fuse classified sensor data is out of scope for a public-data demonstration platform.
- If the mission requires guaranteed detection claims ("you will catch every dark vessel"), decline plainly; the platform flags and explains, humans decide.

## Proposed next step

A bounded EEZ-shaped replay demonstration: public archive AIS for a comparable coastal region, planted dark-period and rendezvous events, flags with full reason evidence reaching the review queue, and the isolation design walked through on paper against their sovereignty requirements.
