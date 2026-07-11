# Case study: Meridian Bay Port Authority pilots corridor and dark-vessel monitoring

> SIMULATED: this customer, every person named, the engagement, and all findings below are fictional, written to demonstrate how a Harbormaster pilot would run. Illustrative values are labeled illustrative and are not measurements. This is not a real deployment, not a real customer, and not ESRI work, ESRI data, or an ESRI client. Every detector and flow referenced is real and exists in this repository; a status footnote at the end says which paths have run live and which have not. See `docs/HONESTY.md`.

## The request

Meridian Bay Port Authority (fictional; persona in `discovery-brief-port-authority.md`) asked for a bounded pilot after two near-miss incidents: flag vessels that leave the dredged approach corridor, treat AIS dark periods near the anchorage as events worth review rather than missing data, and give the watchfloor a review queue where every flag carries evidence an operator can check against the chart. Their own vessel interest list had to drive flags too, with changes taking effect in seconds.

## Data in scope

- Public historical AIS for a region shaped like their approach (MarineCadastre archive replay), used both for baselining and for the demonstration replay.
- A corridor graph for the approach and anchorage derived from public NOAA electronic navigational charts: waypoint nodes and lane edges, the platform's frozen GTRA-style graph build.
- The authority's interest list, entered by their analysts into the registry (vessels, watchlist reasons, severities); no commercial or private feed involved.

## How the pipeline handled it

Replayed AIS flows through Kinesis into the Flink feature job, which computes per-vessel kinematics and applies the cheap physical-plausibility gate first, so garbage tracks never reach the scorer. Each event then hits the deterministic scoring service, where the planner routes it through the inline detectors:

- S-KBM kinematic gate: reported movement that is physically impossible raises `implausible_speed` with the offending kinematics as evidence.
- STAGD-lineage gap detection (with dynamic region merge): an abnormal dark period raises `abnormal_gap`, and the space-time prism bounds where the vessel could feasibly have been while dark.
- TGARD / DC-TGARD rendezvous detection: two vessels whose prisms intersect during overlapping gaps raise a rendezvous hypothesis for review.
- Corridor deviation: positions off the NOAA-derived corridor raise `off_corridor`; arrival at a node the lane structure does not expect raises `unexpected_node`.
- Watchlist and sanctions reasons: the scorer reads the online store (kept fresh from the registry by the CDC pipeline), raising `watchlist_hit` or `sanctions_hit` when the interest list matches.

Reason severities fuse by noisy-OR into the score; items crossing the review threshold land in the Postgres-backed HITL queue, where watchfloor reviewers see the reasons, the evidence, and the map, and record a verdict. Asynchronously, the Pi-DPM head can add a learned second opinion via the SageMaker async endpoint; it is fail-open, so its absence never blocks the queue.

## Findings from the pilot replay (illustrative)

- The planted deviation case: a bulk carrier left the corridor eastbound and went dark for a sustained window near the anchorage. It flagged on `off_corridor` plus `abnormal_gap`; noisy-OR pushed the combined score well above the review threshold, and the reviewer confirmed it. This mirrors the platform's real W1 live-run shape (an `off_corridor` event scored 1.0 reaching HITL end to end).
- The interest-list case: an analyst added a vessel to the watchlist mid-replay; its next scored event carried `watchlist_hit` at high severity. The flag-to-scored freshness target for this path is about 5 seconds (the CDC pipeline's built acceptance target; see the status footnote).
- The false-positive case: a harbor tug flagged `unexpected_node` while working a berth shift. The reviewer rejected it, and the verdict persisted, exactly the disagreement data the Phase 4 flywheel consumes to improve alert quality over time.
- The rendezvous case: two fishing vessels with overlapping dark windows and intersecting feasibility prisms raised a TGARD hypothesis; the reviewer marked it unresolved pending patrol correlation, a verdict state the queue supports rather than forcing a binary call.

## What the customer changed as a result (illustrative)

The watchfloor moved from watching a raw chart to working a queue: deviations surfaced without a person staring at the display, dark periods near the anchorage became reviewable events with feasibility bounds, and rejected flags stopped recurring silently because verdicts feed the improvement loop. The authority's asked-for next step was pushing confirmed flags into their existing VTS display, which is an open integration item, not a built one.

## Status footnote (real platform state behind this simulated story)

- Live-verified: the replay-to-HITL path including corridor deviation ran against real AWS in the W1 showcase (2026-07-04); the lake backfill and promotion pipeline ran live in W2.
- Built, locally accepted, not AWS-run: the CDC watchlist path. The ~5 s flag-to-scored figure is the acceptance target; the local-stack insert-to-online smoke measured 0.57 s. The AWS MSK showcase has never run.
- Built with a labeled stand-in: the Pi-DPM async endpoint serves a `phase3-demo-standin` checkpoint, never a trained model; deterministic detectors carry the scoring.
- In build (Phase 5): tenant isolation via RLS, per-tenant SLO tiers and drift, and the narrative explanation layer. No number in this case study is a live multi-tenant measurement; those land in the W4 window.
