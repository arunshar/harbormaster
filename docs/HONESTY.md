# Honesty framing (locked)

This document is the single source of truth for how Harbormaster is described, anywhere: the README, a resume bullet, an interview answer, a blog post, or a commit message. It is locked. If any other file in the repository drifts from this framing, this file wins and the other file is corrected.

## The locked statement

ESRI (Summer 2023) is a real company, a real team, and real clients. During that internship the ESRI team shipped the original maritime anomaly detector and the AWS MLOps that ran it. That work is ESRI's. It is not personal work, and it is never presented as personal work.

Harbormaster is a PERSONAL extension built by Arun Sharma after, and separate from, the ESRI engagement. It is:

- Never merged with ESRI code, ESRI data, ESRI infrastructure, or ESRI client deliverables.
- Built from public data sources (live AIS via AISStream, historical AIS via public archives) and original code.
- Clearly labeled as personal in every artifact that could otherwise be read as employer work.

The relationship is "inspired by, and a learning extension of, real work I did at ESRI," not "a continuation of ESRI's product."

## What Harbormaster closes, and what it does not

Harbormaster exists to close concrete, demonstrable platform-engineering gaps. Stating both sides honestly is the point.

**Closes (real skills, demonstrated by the build):**

- Change-data-capture (CDC): RDS plus Debezium, log-based capture into the streaming plane.
- Streaming: AISStream to Fargate to Kinesis to Flink, with a real feature plane.
- Production distributed systems: multi-service, multi-plane system with failure handling and backpressure.
- MLOps: model promotion from the MSI training plane into AWS serving, async inference, model registry discipline.
- Observability: metrics, traces, dashboards, and alerting across both planes.

**Does NOT close (explicitly out of scope, never claimed):**

- A sharded query router. Harbormaster does not implement query sharding or a routing layer across shards.
- A consensus implementation. Harbormaster does not implement Raft, Paxos, or any consensus protocol. Where coordination is needed it uses managed services, and that reliance is stated plainly.

If asked "does this prove you can build a consensus system or a sharded query router," the honest answer is no, and Harbormaster does not pretend otherwise.

## Real versus simulated: labeling rules

Some parts of Harbormaster are real engineering. Some parts, especially later-phase demonstrations, are simulated. The rule is that the reader never has to guess which is which.

- **Real and unlabeled by default:** the infrastructure code, the streaming and CDC pipelines, the serving stack, the observability wiring, the cost guardrails. These run against a real AWS account and process real public AIS data.
- **Simulated and always labeled:** customer personas, client names, business case studies, forward-deployed-engineer (FDE) scenarios, any "a customer asked us to..." narrative. Every such artifact carries an explicit "SIMULATED" label inline, at the top of the file or section where it appears.
- **Numbers are quoted, not inflated.** Use continental-scale or the actual figures (~150K ships tracked, ~600 GB of historical AIS). Never claim petabyte scale. If a number is an estimate, say estimate.
- **No employer bleed-through.** No ESRI client names, no ESRI internal project names, no ESRI-private datasets, no ESRI architecture diagrams. If a detail came from ESRI and is not public, it does not appear here.

## What the shared internship materials document (grounded 2026-06-19)

Arun shared his internship deliverable folder, the LaTeX report, and the reference paper. A close five-reader analysis (preserved in docs/internship/) establishes what is backed by a shareable artifact, which matters for both honesty and for what Harbormaster can openly reproduce.

- **Documented and shareable: the waypoint-detection work.** Ramer-Douglas-Peucker line simplification with a novel per-track adaptive tolerance (the standard deviation of point-to-chord distances), plus change-in-bearing, CUSUM, and Mahalanobis variants, each followed by HDBSCAN clustering and centroid waypoints. Ground truth built from NOAA Electronic Navigational Charts (chart IDs 1117A, 11340, 11360, 411, 25671 LE, 11328, 11330, 18740, 530) via polygon-to-centerline shipping-lane extraction. Real result: Line Simplification + HDBSCAN recovered 31 of 41 chart ground-truth waypoints (3 misses had no AIS), RDP recall up to ~0.99 at a 1-std tolerance versus <=0.60 for bearing change, on MarineCadastre AIS. The GTRA-style corridor graph (waypoint nodes, sea-lane edges) is written up as the stated next step, not a benchmarked result.
- **Real but NOT in the shared materials: the full GTRA + Transformer/Evidential-Deep-Learning detector and its figures** (54.76% to 73.02% accuracy, 40% faster route optimization, ~500M records). Per Arun, that portion of the internship was not permitted to be shared, so there is no shareable artifact for it. Treat these as described-at-architecture-granularity only, never as a metric Arun can show, and be aware an interviewer cannot be handed proof of them. They are not repeated in any Harbormaster artifact as a corroborated ESRI deliverable result; Harbormaster re-creates an EDL-flavored detector personally (Pi-DPM).
- **Bathymetry and weather were internship-identified context, not modeled then:** bathymetry appeared as mentor interpretation of why lanes are used (seabed depth, vessel draft), weather only as noise to filter and a future "out of seasonal activity" idea. Harbormaster now models both as personal corridor-graph enrichments on public data.

Corridor boundary: the GTRA corridor idea and the NOAA-chart ground-truth method are public-paper plus internship inspiration ([ESRI / company], describe-only). Harbormaster's Corridor / Route-Graph Preprocessing stage is an original re-implementation on public NOAA and MarineCadastre data ([Harbormaster / personal]).

## The gap talk-track (exact wording)

Use this when asked, in an interview or a review, what this project proves and what it does not. It is the honest, non-defensive version.

> "At ESRI in summer 2023 I worked on a real maritime anomaly detector and the AWS MLOps around it, on a real team with real clients, so that part is company work and I keep it separate. Harbormaster is my personal extension of that problem, built on public AIS data. I used it to close the platform gaps I knew I had: CDC with Debezium, streaming with Kinesis and Flink, a real distributed serving plane, MLOps from training to async inference, and observability across the whole thing. I am deliberate about what it does not prove: I did not build a sharded query router and I did not implement a consensus protocol, I lean on managed services for coordination, and I will say so directly. The training is on MSI because I have no GPU budget on AWS, and the whole thing runs under a hard $75 a month cost cap that I built before I built anything else."

## Phase 1 and Phase 3 AWS showcases run live (2026-07-04)

The "Closes" line's MLOps claim (model promotion, async inference, model registry discipline) moved from designed-and-tested-against-fakes to actually run against real AWS: a live EMR Serverless backfill (Great Expectations gate proven to block a bad-data fixture with zero rows written), a live SageMaker async endpoint with real scale-to-zero autoscaling (both directions, 0-to-1 and 1-to-0, confirmed via real CloudWatch alarm data), a real Model Package Group (fixed 2026-07-04, closing an external audit's fix-before-demo finding, HM3-AUDIT-02), and the real promotion state machine (holdout gate, shadow, weighted canary 5/25/50/100) run against the live endpoint end to end. The endpoint served a labeled `phase3-demo-standin` model throughout, never a real trained checkpoint; the claim this section supports is the infrastructure and promotion discipline, not model quality. Phase 1's streaming plane (Kinesis, Flink, the scoring service) also ran live for the first time this window, with a real planted anomaly reaching the HITL queue end to end. Phase 2's CDC pipeline (below) remains local-stack-only; its AWS MSK showcase has not been run, and no claim here implies otherwise.

## Multigres cover-note update (Phase 2 shipped, 2026-07-03)

The CDC pipeline is now BUILT, not planned: Postgres 16 logical decoding (pgoutput, explicit publication) -> Debezium on Kafka Connect -> an idempotent, LSN-guarded consumer -> DynamoDB/Redis online stores + an Iceberg cdc_audit table, with pg_replication_slots lag alerting and two drills run live (docs/drills/, PLATFORM_WAR_STORIES.md P9 + P10). The gap talk track is therefore: "I have now built a real change-data-capture pipeline in a production-shaped personal platform, logical decoding, at-least-once transport with an idempotent LSN-guarded sink, replay-safe, restart-safe, delete-safe, with slot-lag alerting. What I still have not built, and will say so directly, is a sharded query router and a consensus implementation; that is Vitess/Multigres territory, and Harbormaster deliberately consumes managed Postgres rather than re-implementing it." The two out-of-scope items above are unchanged. The cover note itself now carries this language: it was recovered on 2026-07-03 from the 2026-06-19 session transcript (the file had been lost in a cleanup) to ~/.claude/skills/temporal-interview-prep/references/supabase-multigres-cover-note.md, its gap paragraph updated to the shipped-CDC wording, and the restored set backed up to the private temporal-prep-arc repo.
