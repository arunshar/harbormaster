# System design decisions

This document maps every significant Harbormaster decision to its established distributed-systems pattern, the canonical source that names and argues for that pattern, and the staff-level reasoning a committee or a senior interviewer expects to hear. The goal is twofold: build the platform on good practice from day one, and be able to defend each choice in a 45-minute system-design interview without hand-waving.

Harbormaster is a personal maritime anomaly-detection platform (see `docs/HONESTY.md` for the real-versus-simulated framing and the ESRI boundary). It ingests live AIS vessel traffic (around 150K ships), serves spatial anomaly detectors over a streaming feature plane on AWS, and trains heavy models off-cloud on MSI. It is continental-scale, not petabyte-scale; the honesty rule (numbers are quoted, not inflated) applies to this document too.

## Why patterns matter and how to use this doc

A pattern is a named, reusable answer to a recurring design problem, along with the context in which it applies and the tradeoff it imposes. Patterns matter for three reasons. First, they are compressed experience: someone already paid for the mistake, wrote down the fix, and gave it a name, so you inherit the lesson instead of rediscovering it in production (the Harbormaster war stories in `PLATFORM_WAR_STORIES.md` are exactly these lessons, several of them anticipated before the build hits them). Second, a shared vocabulary lets a team and an interviewer reason at a higher altitude: saying "idempotent receiver" conveys a precise contract that would otherwise take a paragraph. Third, knowing the pattern means knowing its tradeoff, so you can say out loud what you are giving up, which is the single clearest signal of seniority.

How to read an entry. Each Decision Record below has a fixed shape:

- **Decision:** the concrete choice Harbormaster makes.
- **Pattern and source:** the named pattern and the canonical citation (author, work, chapter or URL).
- **Staff-level reasoning:** why this is the right move, argued the way a principal engineer would.
- **Tradeoffs and alternatives considered:** what we gave up and what we rejected, honestly.
- **How Harbormaster instantiates it:** the specific AWS or code mechanism.
- **Interview soundbite:** one line you can say under pressure that signals you understand the pattern, not just the name.

A note on sources. Where a source is a public article (Martin Fowler's bliki, microservices.io, the Google SRE book, HelloInterview's free framework), the URL is given and you should read it. Where a source is a book (Kleppmann's *Designing Data-Intensive Applications*, Newman's *Building Microservices*, Nygard's *Release It!*, Fowler and Joshi's *Patterns of Distributed Systems*), it is referenced by chapter or pattern name only; do not expect quoted text. HelloInterview premium ("System Design in a Hurry" deep-dives) is paywalled; you have access, so this doc points you to the exact topic to read rather than reproducing the prose.

---

## Decision records

### DR-1: CDC pipeline (RDS Postgres logical decoding to derived stores)

**Decision.** Operational state lives in RDS Postgres. Changes are captured by logical decoding and Debezium, published to Kinesis as a change stream, consumed by an idempotent LSN-guarded consumer, and fanned out to derived stores: Feast/DynamoDB (online features), Redis (hot cache), and an Iceberg `cdc_audit` table (append-only history).

**Pattern and source.** Change Data Capture and the dual-write problem; the log-based message broker; derived-data synchronization. Kleppmann, *Designing Data-Intensive Applications*, ch 11 (Stream Processing: change data capture, log-based brokers) and ch 12 (The Future of Data Systems: derived data, unbundling the database). Chris Richardson, microservices.io, Transactional Outbox (https://microservices.io/patterns/data/transactional-outbox.html) for the dual-write framing. HelloInterview Core Concepts: change data capture (hellointerview.com/learn/system-design/core-concepts).

**Staff-level reasoning.** The naive design writes to Postgres and then writes to the cache and the feature store from application code. That is a dual write: two systems updated by two separate operations with no shared transaction, so any crash between them leaves the stores inconsistent, and there is no retry that fixes it because you do not know which write landed. CDC removes the dual write by making the database's own commit log the single source of truth: you write once, to Postgres, and every derived store is a deterministic function of the ordered change log. The log is the contract; the stores are projections. This is the same insight as "unbundling the database" (Kleppmann ch 12): the storage engine, the index, and the cache are separated and re-synchronized through a log rather than coupled through synchronous writes.

**Tradeoffs and alternatives considered.** The alternative is the Transactional Outbox: write the business row and an outbox row in one local transaction, then relay the outbox to the broker. Outbox is the right call when you control the application's write path and want application-level events. Harbormaster chose log-based CDC instead because it captures every change to operational state with no application changes and no risk of a developer forgetting to write the outbox row; the cost is operational (logical decoding load on Postgres, connector to run, schema-evolution discipline). The tradeoff CDC imposes is eventual consistency between the write model and the read models (see DR-4 and DR-16) and a cold-start snapshot cost (war story P3).

**How Harbormaster instantiates it.** RDS Postgres with `wal_level=logical` and replica identity set; Debezium reads the WAL via logical decoding and publishes to Kinesis; the consumer upserts into DynamoDB/Feast and Redis and appends to Iceberg `cdc_audit`. Phase 3 in the README.

**Interview soundbite.** "I write once to Postgres and let the WAL be the source of truth; every derived store is a projection of the log, so I never have a dual write to keep consistent by hand."

### DR-2: Idempotent consumer (LSN-guarded upsert)

**Decision.** The CDC consumer is idempotent: it upserts by primary key, guards application with a monotonic `last_applied_lsn` (skip any record whose LSN is not greater than what was already applied), commits the stream offset only after the sink acknowledges the write, and represents deletes as tombstones.

**Pattern and source.** Idempotent Receiver. Fowler and Joshi, *Patterns of Distributed Systems*, "Idempotent Receiver" (https://martinfowler.com/articles/patterns-of-distributed-systems/idempotent-receiver.html). Kleppmann, *Designing Data-Intensive Applications*, ch 11 (exactly-once / effectively-once semantics, idempotence as the practical mechanism). Versioned Value / High-Water Mark (the `last_applied_lsn` guard is a high-water mark over the change log): *Patterns of Distributed Systems*, "High-Water Mark" and "Versioned Value."

**Staff-level reasoning.** Kinesis, like any log-based broker, gives at-least-once delivery: on consumer restart or rebalance you will re-read records you already processed. True exactly-once across a network and an external sink is not achievable in general, so the honest target is effectively-once: at-least-once delivery plus idempotent application equals the same end state no matter how many times a record is redelivered. Two mechanisms make the consumer idempotent. Upsert-by-PK makes a re-applied insert a no-op rather than a duplicate row. The monotonic `last_applied_lsn` guard makes out-of-order or stale redeliveries safe by rejecting anything not strictly newer than the last applied position, which is a high-water mark over the WAL's log sequence numbers. The offset-commit-after-sink-ack ordering closes the last gap: if you commit the offset before the sink write lands and then crash, you have lost the record (it will never be redelivered); committing only after the sink acknowledges means a crash leaves the offset un-advanced and the record is safely re-read.

**Tradeoffs and alternatives considered.** The alternative "exactly-once" framings (broker transactions, two-phase commit to the sink) add coordination cost and still reduce, in practice, to idempotent writes plus deduplication. Choosing effectively-once keeps the consumer simple and fast. The cost is that you must design every sink write to be idempotent (the LSN guard plus upsert), and you must store the high-water mark durably alongside the sink. Tombstone deletes cost extra storage and require downstream readers to honor the tombstone, but they preserve the log's append-only property.

**How Harbormaster instantiates it.** Consumer keeps `last_applied_lsn` per key (or per partition) in the sink; applies a record only if its LSN exceeds the stored value; upserts to DynamoDB/Feast and Redis; appends to Iceberg with the LSN; commits the Kinesis iterator position only after the sink ack. Deletes become tombstone rows.

**Interview soundbite.** "Kinesis is at-least-once, so I make the consumer effectively-once: upsert by key, reject anything not newer than my last-applied LSN, and commit the offset only after the sink acks."

### DR-3: Model-promotion pipeline and the retraining flywheel

**Decision.** A model trained on MSI is promoted through a multi-stage gate: a MIRROR-holdout quality gate, then shadow (parallel run, no production effect), then canary at 5%, 25%, 50% traffic, then full rollout via Argo CD. A separate closed loop runs continuously: drift detection triggers human-in-the-loop (HITL) review, which feeds Pi-GRPO retraining, which produces the next candidate that re-enters the promotion gate.

**Pattern and source.** Saga orchestration versus choreography; compensating transactions; durable execution / workflow engines: Chris Richardson, microservices.io, Saga (https://microservices.io/patterns/data/saga.html); Sam Newman, *Building Microservices* 2nd ed, sagas (orchestration vs choreography) and deployment patterns; HelloInterview, "Multi-step Processes" (https://hellointerview.com/learn/system-design/patterns/multi-step-processes). Parallel Run / shadowing: Newman, *Building Microservices* 2nd ed (deployment). Canary Release: Fowler, https://martinfowler.com/bliki/CanaryRelease.html. Blue-Green Deployment: Fowler, https://martinfowler.com/bliki/BlueGreenDeployment.html. See the dedicated saga deep-dive below for the full treatment.

**Staff-level reasoning.** Promotion is a multi-step process where each step can fail and some steps have side effects that must be undone. That is precisely a saga: a sequence of local steps, each with a compensating action, coordinated so that a failure anywhere triggers the compensations for the steps already taken. The compensation for "shifted 25% of traffic to the new model" is "shift it back" (auto-rollback). Modeling promotion as a saga with explicit compensations is what makes auto-rollback a first-class, tested path rather than an incident-time scramble. The retraining flywheel is a longer-lived saga: drift to HITL to retrain to re-promote, with the human approval as a deliberate durable wait.

**Tradeoffs and alternatives considered.** Orchestration (a central coordinator drives the steps) versus choreography (services react to events) is the core saga choice; Harbormaster uses orchestration for promotion because the sequence is fixed, the rollback logic must be auditable, and a single place to see "where is this promotion" is worth the coupling. Canary versus blue-green: blue-green flips all traffic at once between two identical environments (fast rollback, but no graduated exposure and double the resources during the flip); canary exposes a small percentage first and ramps, which catches model-quality regressions that only appear under real traffic. Harbormaster uses canary for model promotion (quality risk is graduated and traffic-dependent) and would reserve blue-green for stateless infra swaps. The cost of the saga approach is the orchestrator and the requirement that every step be idempotent and every compensation be safe to run more than once.

**How Harbormaster instantiates it.** Argo CD drives the rollout; shadow runs the candidate in parallel against live traffic with its output discarded (parallel run); canary weights step 5/25/50; burn-rate on the SLO (DR-13) is the auto-rollback trigger, which is the compensating transaction. The flywheel's retraining is Pi-GRPO on MSI; promotion re-enters the same gate.

**Interview soundbite.** "Promotion is a saga: shadow, then canary 5/25/50, with auto-rollback as the compensating transaction, orchestrated so rollback is a tested path, not an incident-time improvisation."

### DR-4: Read models versus write model (CQRS)

**Decision.** The write model is Postgres (the model registry and operational state). The read models are the Feast online feature store, DynamoDB, and a Redis hot cache. Writes go to Postgres; serving reads go to the online store and cache; the two are connected by the CDC pipeline (DR-1).

**Pattern and source.** Command Query Responsibility Segregation (CQRS) and materialized views. Fowler, https://martinfowler.com/bliki/CQRS.html. Chris Richardson, microservices.io, CQRS (https://microservices.io/patterns/data/cqrs.html). Read-your-writes consistency: Kleppmann, *Designing Data-Intensive Applications*, ch 5 (Replication, consistency guarantees).

**Staff-level reasoning.** The write side and the read side have different shapes. The write side wants transactional integrity, relational constraints, and a normalized registry; Postgres is right for that. The read side wants single-digit-millisecond point lookups of per-vessel features at serving time; a normalized relational query is the wrong tool, and a denormalized key-value online store is the right one. CQRS makes this split explicit: optimize each side independently and accept that the read model is a derived, eventually-consistent projection of the write model. The online feature store is, in CQRS terms, a materialized view maintained by the CDC stream.

**Tradeoffs and alternatives considered.** The alternative is one store serving both paths: simpler, strongly consistent, but it forces a compromise schema and couples serving latency to the write store's load. CQRS buys independent scaling and latency at the cost of eventual consistency between sides and the machinery to keep the read model fresh (DR-1, DR-2). The sharp edge is read-your-writes: a client that just wrote to Postgres may not yet see the change in the online store. Harbormaster accepts this because serving reads are vessel features that tolerate sub-second staleness; where read-your-writes matters (a just-promoted model's metadata), the serving path reads the registry directly. CQRS is overkill for a CRUD app; it earns its keep here because the read and write workloads genuinely diverge.

**How Harbormaster instantiates it.** Postgres registry is the command side; Feast/DynamoDB and Redis are the query side; CDC keeps them in sync. GeoTrace front door reads the online store, not Postgres, on the hot path.

**Interview soundbite.** "Write to Postgres, read from the online store; they are different workloads, so I treat the online store as a materialized view kept fresh by CDC, and I accept eventual consistency on the read side."

### DR-5: Iceberg `cdc_audit` log and the anomaly event stream (event sourcing)

**Decision.** The Iceberg `cdc_audit` table is append-only: it records the full ordered history of changes, not just current state. The anomaly event stream is likewise a log of detected events. State is derived from these logs.

**Pattern and source.** Event Sourcing; the log as source of truth; unbundling the database. Fowler, Event Sourcing (https://martinfowler.com/eaaDev/EventSourcing.html). Kleppmann, *Designing Data-Intensive Applications*, ch 11 (event sourcing, log-based derivation) and ch 12 (derived data, unbundling the database).

**Staff-level reasoning.** Storing current state only is lossy: you can never answer "what did the system believe at time T" or rebuild a derived store after a bug, because the history is gone. An append-only log keeps every change as an immutable fact; current state becomes a fold over the log, and any derived view can be rebuilt by replaying. For an anomaly platform this is not a luxury: auditability ("why did we flag this vessel, and on what evidence") and reproducible training pulls (DR-12) both require the history, not just the snapshot. Iceberg's snapshot isolation and time-travel make the log queryable and reproducible at a point in time.

**Tradeoffs and alternatives considered.** The alternative is mutable current-state tables: smaller, simpler, but unauditable and unreplayable. Event sourcing costs storage (the full history) and adds the compaction and snapshot-expiry maintenance burden (war story P6: a streaming sink into a table format is a maintenance commitment). It also pushes complexity onto readers, who must fold the log or query the right snapshot. Harbormaster accepts this because audit and reproducibility are core requirements; it does not event-source everything (the registry is current-state in Postgres), only the audit and anomaly logs where history is the product.

**How Harbormaster instantiates it.** Firehose lands CDC and events into S3/Iceberg; `cdc_audit` is append-only with LSNs; Iceberg snapshots give time-travel for reproducible MSI training pulls; scheduled compaction and snapshot expiry manage the small-file cost.

**Interview soundbite.** "The audit table is an append-only event log, so current state is a fold over it and I can replay to rebuild any derived store or reproduce exactly what the system saw at training time."

### DR-6: Streaming ingestion with Flink backpressure and the P_phys cheap-gate

**Decision.** Flink computes streaming features with event-time windows and watermarks; backpressure propagates naturally when a downstream stage is slow. A cheap physics-based gate, `P_phys`, runs first and sheds or short-circuits work that cannot be anomalous, before the expensive model is consulted.

**Pattern and source.** Backpressure / flow control: Kleppmann, *Designing Data-Intensive Applications*, ch 11 (stream processing, handling fast producers). Load Shedding and Steady State: Nygard, *Release It!* (stability patterns: Load Shedding, Steady State). Watermarks and event-time windows: Kleppmann ch 11 (reasoning about time in streams).

**Staff-level reasoning.** A streaming system has a producer (AIS at its own rate) and a consumer (feature computation plus model calls) that can fall behind. Two failure modes follow. Without flow control, a slow consumer either drops data or exhausts memory buffering it; backpressure is the disciplined answer, propagating slowness upstream so the producer is throttled rather than the system crashing. Flink gives this natively through its bounded buffers. The second mechanism, load shedding, is for the case where even backpressure is not enough and you must drop work to protect the system; the senior move is to drop the cheapest-to-drop, least-valuable work first. `P_phys` is exactly that: a cheap physics check that decides most positions are obviously normal and never need the expensive Pi-DPM call, so the expensive path only sees plausible anomalies. This is load shedding by relevance, not random drop.

**Tradeoffs and alternatives considered.** The alternative to backpressure is an unbounded queue (postpones the problem until memory runs out) or silent drops (data loss, war story P4 in spirit). Backpressure trades throughput-under-overload for stability and no loss. The alternative to the cheap-gate is calling the heavy model on every event: simpler, but it wastes the expensive path on obvious normals and makes overload far more likely. `P_phys` costs a small false-negative risk if the gate is too aggressive, mitigated by tuning the gate conservatively and auditing what it filters. Watermarks themselves carry the classic risk (war story P2): adversarial timestamps can stall them, so they need bounded out-of-orderness and an idleness timeout.

**How Harbormaster instantiates it.** Flink on Kinesis Data Analytics, keyed per-vessel state, event-time windows with bounded-out-of-orderness watermarks; `P_phys` runs inline as the first filter; only events that pass the gate reach the async model call (DR-8).

**Interview soundbite.** "Flink backpressures naturally, and I shed load by relevance with a cheap physics gate so the expensive model only ever sees plausible anomalies, not every position report."

### DR-7: Multi-tenant isolation (bulkhead, default-deny)

**Decision.** Every record and request carries a `tenant_id`; access is default-deny (a request with no matching tenant grant is rejected, fail-closed). Tenants get per-tenant resource pools and per-tenant models so one tenant's load or failure cannot starve another.

**Pattern and source.** Bulkhead: Nygard, *Release It!* (Bulkhead stability pattern); Newman, *Building Microservices* 2nd ed (resilience: bulkhead). Cell-based architecture / shuffle sharding (the isolation generalization). Default-deny / fail-closed: standard security posture.

**Staff-level reasoning.** A bulkhead, named for a ship's watertight compartment, contains a failure so it cannot sink the whole vessel. Without isolation, one noisy or compromised tenant consumes a shared pool (connections, threads, model capacity) and degrades everyone: a single tenant becomes a single point of failure for all tenants. Per-tenant pools partition the blast radius so the damage stops at the compartment wall. Default-deny is the security counterpart: the safe default when a tenant grant is missing or ambiguous is to refuse, not to serve, because a fail-open default leaks data across the tenant boundary, which for a maritime tracking platform is the worst possible bug.

**Tradeoffs and alternatives considered.** A shared pool is cheaper and simpler and gives better average utilization; the bulkhead trades some utilization (idle capacity reserved per tenant) for guaranteed isolation. Full cell-based isolation (a separate stack per tenant) is the strongest form but the most expensive; Harbormaster uses per-tenant pools and models within a shared control plane as the proportionate middle. Default-deny costs occasional friction (a legitimately new tenant is refused until granted), which is the correct direction to fail.

**How Harbormaster instantiates it.** `tenant_id` stamped at ingest and carried through the pipeline; per-tenant pools and per-tenant models on the serving plane; authorization checks default to deny when no tenant grant matches.

**Interview soundbite.** "Each tenant is a bulkhead with its own pool and model, and authorization is default-deny, so one tenant's overload or a missing grant fails closed instead of bleeding across the boundary."

### DR-8: Async model call from the stream to the serving endpoint

**Decision.** The stream calls the heavy model (Pi-DPM on a SageMaker asynchronous multi-model endpoint) through a circuit breaker with a timeout, bounded retries with exponential backoff and jitter, and a bounded async queue. "No result within SLA" is treated as an explicit failure, not a success.

**Pattern and source.** Circuit Breaker: Fowler, https://martinfowler.com/bliki/CircuitBreaker.html; Nygard, *Release It!* (Circuit Breaker). Timeout and Retry: Nygard, *Release It!* (Timeout); Newman, *Building Microservices* 2nd ed (resilience: timeouts, circuit breaker, drawing on Nygard). Backoff with jitter and the bounded queue: standard resilience practice over an async endpoint.

**Staff-level reasoning.** Any synchronous call across a process boundary can hang, and a hung call holds a resource (a thread, a slot) that, multiplied under load, exhausts the caller; this is how one slow dependency cascades into a full outage. A timeout bounds the wait. A circuit breaker goes further: after a threshold of failures it opens and fails fast for a cooldown, so the caller stops hammering a sick dependency and stops piling up blocked work, then half-opens to test recovery. Retries handle transient blips, but naive retries cause a thundering herd that synchronizes on the dependency's recovery; exponential backoff with jitter spreads the retries out so they do not all hit at once. Because the endpoint is asynchronous, it is a queue, and a queue has a drop policy (war story P4): if you do not wire the failure notification you lose requests blind, so "no result within SLA" must be an explicit, observable failure that triggers a retry, not a silent success.

**Tradeoffs and alternatives considered.** Synchronous real-time inference would give lower latency per call but cannot absorb bursts and would force over-provisioning to avoid drops, blowing the cost cap. The async endpoint absorbs bursts in its queue at the cost of higher and more variable latency, which is acceptable because detection is not real-time-critical and the cheap gate (DR-6) already filtered the obvious normals. Circuit breakers add a failure mode of their own (an over-eager breaker rejects healthy traffic), tuned by threshold and cooldown. Retries without idempotency would duplicate work; the consumer's idempotence (DR-2) makes retries safe.

**How Harbormaster instantiates it.** SageMaker async MME for Pi-DPM with success and failure SNS topics wired; autoscaling on backlog-per-instance; caller applies timeout, circuit breaker, and jittered backoff; SLA breach is an explicit retry path.

**Interview soundbite.** "The heavy model call goes through a timeout and a circuit breaker with jittered backoff, and because it is an async queue I treat 'no result in SLA' as an explicit failure, not a silent drop."

### DR-9: Kinesis shard / Kafka partition design and the MMSI hot-shard incident

**Decision.** The partition key for the AIS stream is an MMSI-derived hash (high cardinality), not a coarse region code. Shard count is sized to throughput, and a per-shard hot-key metric makes skew visible before it throttles.

**Pattern and source.** Partitioning, skew, and hot spots: Kleppmann, *Designing Data-Intensive Applications*, ch 6 (Partitioning: skew, hot spots, partitioning by hash of key). Consumer-group rebalancing: Kleppmann ch 11. Partition-key choice: war story P1 (the MMSI hot-shard incident).

**Staff-level reasoning.** A partitioned log spreads load by key, and the entire scheme lives or dies on the key choice. A low-cardinality or skewed key (a region code, where a few dense shipping lanes carry most traffic) maps disproportionate load onto one shard: that shard throttles (`ProvisionedThroughputExceeded`) while siblings idle. The seductive wrong fix is to add shards, but total throughput was never the problem; the key distribution was, so more shards just redistribute the same skew (war story P1: shard count treats a symptom, partition-key cardinality is the disease). The right fix is a high-cardinality key (a hash of MMSI) so per-vessel traffic spreads evenly. The second discipline is observability: graph per-shard throughput, not just aggregate, because aggregate health hides a single hot shard until it throttles.

**Tradeoffs and alternatives considered.** Hashing by MMSI spreads load but scatters a single vessel's records across consumers unless you key by vessel deliberately; Harbormaster keys per-vessel because per-vessel ordering and keyed state matter for feature computation, and MMSI cardinality (around 150K) is high enough to avoid hot shards. An alternative, explicit hot-key splitting (salting the few hottest keys), is more complex and reserved for the case where one vessel genuinely dominates, which AIS does not exhibit. Rebalancing during scale events briefly disrupts consumers; this is accepted and handled by idempotent processing (DR-2).

**How Harbormaster instantiates it.** Kinesis partition key is an MMSI-derived hash; per-shard throughput and a hot-key metric are dashboards; shard count is sized from the capacity estimate (see the worked example below).

**Interview soundbite.** "I key by an MMSI hash, not a region code, because skew throttles a single shard while the others idle; shard count treats the symptom, key cardinality is the cure."

### DR-10: CDC event schema (encoding and evolution)

**Decision.** CDC events use an explicit, versioned schema managed through a schema registry, with backward and forward compatibility enforced so producers and consumers can be deployed independently.

**Pattern and source.** Encoding and Evolution; schema registry; backward / forward compatibility. Kleppmann, *Designing Data-Intensive Applications*, ch 4 (Encoding and Evolution: schema evolution, backward and forward compatibility, Avro/Protobuf).

**Staff-level reasoning.** In a streaming system, producers and consumers are deployed at different times and run different code versions simultaneously, so the schema must evolve without a flag-day where everything redeploys at once. Two compatibility directions matter. Backward compatibility means new consumer code can read old data (so you can deploy the consumer first). Forward compatibility means old consumer code can read new data (so a producer can add a field before all consumers know about it). Honoring both means schema changes are limited to safe operations: add optional fields, never remove or repurpose a field's meaning. A schema registry enforces this at publish time, turning an incompatible change into a deploy-time error instead of a 3 a.m. deserialization failure in production.

**Tradeoffs and alternatives considered.** Schemaless JSON is easy to start with but pushes every compatibility decision to runtime and to tribal knowledge, which is where silent data-corruption bugs live. A registry plus a binary encoding (Avro or Protobuf) costs upfront ceremony and a registry to operate, in exchange for compile-or-publish-time guarantees and compact wire format. Harbormaster accepts the ceremony because CDC events feed the audit log (DR-5), which is the system of record, and a corrupt schema there is unrecoverable. The constraint this imposes on developers is real: no breaking field changes, only additive evolution.

**How Harbormaster instantiates it.** CDC events carry a schema version; a registry enforces backward/forward compatibility on publish; the Iceberg sink uses Iceberg's own schema evolution so the audit table evolves safely alongside.

**Interview soundbite.** "Producers and consumers deploy independently, so the CDC schema is registry-enforced and only evolves additively; backward compatibility lets me deploy the consumer first, forward compatibility lets the producer add a field early."

### DR-11: Rebuilding the ESRI prototype into the platform (strangler fig)

**Decision.** Harbormaster does not rewrite the original maritime detector in one big-bang cutover. It grows the new platform around the problem incrementally, standing up streaming, CDC, serving, and observability as separate phases, and routing functionality across as each new piece proves out. (Per `docs/HONESTY.md`, the ESRI work itself stays separate; this is a personal rebuild of the same problem on public data.)

**Pattern and source.** Strangler Fig Application. Fowler, https://martinfowler.com/bliki/StranglerFigApplication.html.

**Staff-level reasoning.** A big-bang rewrite is the highest-risk way to replace a working system: you carry all the risk until the single cutover, and if it fails you have no incremental value and a hard rollback. The strangler fig (named for the vine that grows around a tree and gradually replaces it) inverts this: build the new system alongside the old, move one capability at a time, and keep both running until the new one has fully taken over. Each phase delivers standalone value and is independently reversible, so risk is paid down continuously instead of all at the end. Harbormaster's phase plan (foundations, streaming, serving, lakehouse/CDC, observability, case studies) is a strangler-fig schedule.

**Tradeoffs and alternatives considered.** A rewrite is simpler to reason about and avoids running two systems in parallel, but the risk profile is unacceptable for anything load-bearing. The strangler fig costs a longer total timeline and the complexity of an interim state where old and new coexist (and sometimes a facade to route between them). Harbormaster accepts the longer timeline because incremental, reversible delivery is the whole point of a learning-grade platform, and because the cost guardrails (DR-13) reward building the cheapest safe thing first.

**How Harbormaster instantiates it.** The phased README roadmap: Phase 0 foundations and FinOps before any spend, then streaming, serving, lakehouse/CDC, observability, and simulated case studies, each phase delivering and de-risking independently.

**Interview soundbite.** "I grow the platform around the problem phase by phase rather than big-bang rewriting it, so every phase delivers value and stays reversible instead of betting everything on one cutover."

### DR-12: Batch backfill, live stream, and replay (lambda vs kappa)

**Decision.** Harbormaster runs a live stream (Flink) for current features, a batch path (EMR) for historical backfill, and the ability to replay history from the Iceberg log to reprocess. The architecture leans toward kappa (reprocess by replaying the log) with a pragmatic batch backfill where reprocessing 600 GB from scratch on the stream would be wasteful.

**Pattern and source.** Lambda versus Kappa architecture; reprocessing. The Lambda architecture is Nathan Marz's coinage; the Kappa architecture is Jay Kreps's ("Questioning the Lambda Architecture," O'Reilly Radar, 2014). Kleppmann, *Designing Data-Intensive Applications*, ch 11 (reprocessing data, the unifying log) and ch 12 (the lambda architecture and its critique, deriving multiple views from a log, maintaining derived state) is the textbook treatment of both. The kappa idea (reprocess by replaying one log rather than maintaining separate batch and stream code) is the natural consequence of the log-as-source-of-truth (DR-5).

**Staff-level reasoning.** Lambda architecture runs two code paths, a batch layer and a speed layer, and merges them; its well-known cost is maintaining the same logic twice in two engines and reconciling their results. Kappa collapses this: if the log is the source of truth and is replayable, you reprocess by replaying it through the same streaming code, so there is one codebase and no reconciliation. Harbormaster's Iceberg audit log (DR-5) is exactly the replayable log kappa needs. The pragmatic exception is large historical backfill: replaying 600 GB through the live stream competes with live traffic and is slow, so a bounded EMR batch job is the right tool for the one-time cold load, while ongoing reprocessing uses replay.

**Tradeoffs and alternatives considered.** Pure lambda buys a battle-tested batch layer at the cost of duplicated logic and drift between the two paths. Pure kappa is cleanest but assumes the log retains enough history and that replay throughput is acceptable; for a multi-hundred-GB cold start it is not, which is why Harbormaster keeps EMR for backfill. The hybrid's cost is having two execution engines (Flink and EMR) to operate, justified because they do genuinely different jobs (continuous vs one-time bulk) rather than duplicating the same logic.

**How Harbormaster instantiates it.** Flink for live features; EMR for the historical 600 GB backfill; Iceberg time-travel snapshots for replay-based reprocessing and reproducible training pulls back to MSI.

**Interview soundbite.** "I lean kappa: the Iceberg log is replayable, so I reprocess through the same streaming code instead of maintaining a separate batch layer, and I only drop to EMR batch for the one-time multi-hundred-GB cold backfill."

### DR-13: SLOs, error budgets, and burn-rate auto-rollback

**Decision.** Serving has explicit SLOs (latency and availability targets). The complement of the SLO is an error budget. Canary auto-rollback and alerting are driven by burn-rate: how fast the current error rate is consuming the budget.

**Pattern and source.** SLOs, error budgets, burn-rate alerting. Google SRE Book (https://sre.google/books), chapters on Service Level Objectives and Alerting on SLOs / burn-rate. The auto-rollback tie-in is the compensating transaction of the promotion saga (DR-3).

**Staff-level reasoning.** "Is the service healthy" is unanswerable without a number; an SLO is that number (for example, 99.9% of inference requests under the latency target over 30 days). The error budget is what makes it actionable: 99.9% available means 0.1% is the budget you are allowed to spend, which reframes reliability from "never fail" (impossible, and it freezes shipping) to "fail within budget" (a quantitative speed limit). Burn-rate alerting is the senior refinement over threshold alerting: instead of paging on a raw error count, you alert on how fast the budget is being consumed, so a fast burn pages immediately (you will exhaust the month's budget in hours) while a slow burn is a ticket, not a 3 a.m. page. Wiring canary auto-rollback to burn-rate makes the rollback decision objective and automatic: a canary that burns budget too fast rolls itself back.

**Tradeoffs and alternatives considered.** Threshold alerting (page when errors exceed N) is simpler but either pages on harmless blips or misses slow bleeds; burn-rate needs multiple windows (fast and slow) tuned correctly, more setup for far better signal-to-noise. The error-budget discipline costs organizational buy-in (you must actually halt risky changes when the budget is spent). Harbormaster's version is lightweight (a personal platform) but the mechanism is the real one, because the canary gate (DR-3) needs an objective rollback trigger.

**How Harbormaster instantiates it.** Latency and availability SLOs on the serving plane; error budget tracked from the SLO; multi-window burn-rate alerts; canary promotion auto-rolls-back when the candidate's burn-rate exceeds threshold.

**Interview soundbite.** "I set an SLO, treat its complement as an error budget, and alert and auto-rollback on burn-rate, so a canary that eats the budget too fast rolls itself back and a slow bleed is a ticket, not a page."

### DR-14: Capacity sizing for the live AIS feed

**Decision.** Shard count, storage growth, and rough cost are derived from a back-of-envelope estimate of the AIS message rate, not guessed. (Full worked example below.)

**Pattern and source.** Back-of-envelope estimation: message rate, shard count, bytes/day, cost. HelloInterview, "System Design in a Hurry," the estimation method within the Delivery Framework (hellointerview.com/learn/system-design). Kinesis sizing follows from the partitioning analysis (DR-9).

**Staff-level reasoning.** Estimation is how you turn "it should scale" into a defensible number, and an interviewer is grading whether you reason in orders of magnitude rather than reaching for precision you cannot have. The method is: state assumptions explicitly (ships, messages per ship per minute, bytes per message), compute the derived rate (messages per second), and size each resource from that single rate (shards from records-per-second and per-shard limits, storage from bytes times rate times seconds-per-day, cost from the resource counts). Doing this before provisioning prevents both under-provisioning (war story P1's throttling) and the far more expensive over-provisioning that blows the cost cap.

**Tradeoffs and alternatives considered.** Guessing or copying someone else's shard count ignores your actual rate and is how you end up paying for idle capacity or throttling under load. The estimate's cost is that it depends on assumptions that may be wrong; the mitigation is to state them so they can be challenged and re-run, and to size with headroom for burst.

**How Harbormaster instantiates it.** See the worked example below; the numbers feed the Kinesis shard count (DR-9), the Iceberg storage plan (DR-5/DR-12), and the FinOps budget ($30 soft / $75 hard).

**Interview soundbite.** "I size from one derived number, the messages-per-second from stated assumptions, then drive shards, storage, and cost from it, with headroom for burst, instead of guessing a shard count."

### DR-15: Serving API design

**Decision.** The serving API uses idempotency keys on writes, cursor-based pagination on list endpoints, explicit versioning, and resource-oriented design.

**Pattern and source.** API design: idempotency keys, pagination, versioning. HelloInterview, API Design (https://hellointerview.com/learn/system-design/core-concepts/api-design). Idempotency keys generalize the Idempotent Receiver (DR-2). Request Pipeline (overlapping requests without head-of-line blocking): Fowler and Joshi, *Patterns of Distributed Systems*, "Request Pipeline."

**Staff-level reasoning.** An API over a network is called by clients that retry, so any non-idempotent write (submit an anomaly report, trigger a promotion) will be sent twice when a client times out and retries; an idempotency key lets the server deduplicate and return the original result, turning at-least-once client behavior into effectively-once semantics at the API boundary, the same principle as DR-2. Cursor (not offset) pagination is correct under a live, changing dataset because offset pagination skips or repeats rows when the underlying data shifts between pages, while a cursor anchors to a stable position. Explicit versioning lets the API evolve without breaking existing clients, the API-surface analogue of schema evolution (DR-10).

**Tradeoffs and alternatives considered.** Offset pagination is simpler and allows random page access but is wrong for a live feed; cursor pagination gives stable iteration at the cost of no jump-to-page-N. Idempotency keys require the server to store seen keys for a window (storage and lookup cost) in exchange for safe client retries. Versioning costs the discipline of supporting old versions during a deprecation window. These are standard, low-controversy choices; the point in an interview is to volunteer them unprompted.

**How Harbormaster instantiates it.** Write endpoints accept an idempotency key and dedupe within a TTL; list endpoints (vessels, events) use opaque cursors; the API is versioned; responses are resource-oriented.

**Interview soundbite.** "Writes take an idempotency key so client retries are safe, lists use cursor pagination because the feed is live and offsets drift, and the API is explicitly versioned so it can evolve without breaking clients."

### DR-16: Consistency choice between Postgres write and online-store read (PACELC)

**Decision.** Harbormaster accepts eventual consistency between the Postgres write model and the online-store read model on the hot serving path, and reserves strong/read-your-writes consistency for the few places that require it (reading just-promoted model metadata from the registry directly).

**Pattern and source.** PACELC; eventual versus strong consistency; read-your-writes; linearizability and quorums. Kleppmann, *Designing Data-Intensive Applications*, ch 9 (Consistency and Consensus: linearizability, quorums) and ch 5 (replication consistency, read-your-writes). PACELC framing and consistency tradeoffs: HelloInterview Core Concepts (consistency, PACELC) (hellointerview.com/learn/system-design/core-concepts).

**Staff-level reasoning.** PACELC extends CAP with the everyday case: if there is a Partition you trade Availability against Consistency, but Else (the normal, no-partition case) you trade Latency against Consistency. That "else" is the one that matters most days, and it forces an explicit choice: strong consistency costs latency (coordination on every read), eventual consistency buys latency at the price of possibly stale reads. Harbormaster's hot path reads per-vessel features that tolerate sub-second staleness, so the latency-favoring choice (eventual consistency on the CDC-fed read model, DR-1/DR-4) is correct. The senior move is not "eventual is fine everywhere": it is to name the few operations that genuinely need read-your-writes (a freshly promoted model's metadata must be visible immediately to the thing serving it) and route those to the strongly-consistent write store directly.

**Tradeoffs and alternatives considered.** Strong consistency everywhere would simplify reasoning but add coordination latency to every serving read and couple read availability to the write store, the opposite of what the read path needs. Eventual everywhere risks a correctness bug where a control-plane action (promotion) is not yet visible; mitigated by reading the registry directly for those operations. The choice is per-operation, not global, which is the whole point of PACELC thinking.

**How Harbormaster instantiates it.** Hot-path feature reads hit the eventually-consistent online store; control-plane reads (model metadata, registry) hit Postgres directly for read-your-writes; the CDC lag between them is monitored.

**Interview soundbite.** "By PACELC, with no partition I am trading latency against consistency, so the hot path reads the eventually-consistent online store, and I route only the handful of read-your-writes operations, like reading a just-promoted model, to Postgres directly."

---

## Saga deep-dive: the promotion saga and the retraining flywheel

This section expands DR-3 because the promotion pipeline and the retraining flywheel are the most interesting distributed-coordination problem in Harbormaster, and "multi-step process with compensations" is one of the highest-leverage patterns to be able to discuss at a staff level.

Sources for this section: Chris Richardson, microservices.io, Saga (https://microservices.io/patterns/data/saga.html); Sam Newman, *Building Microservices* 2nd ed (sagas, orchestration vs choreography; resilience patterns drawing on Nygard's *Release It!*); HelloInterview, "Multi-step Processes" (https://hellointerview.com/learn/system-design/patterns/multi-step-processes), which covers distributed transactions, sagas, workflow engines, and durable execution as a progression.

### Why not a distributed transaction

The textbook way to make "promote the model, shift traffic, update the registry, notify" atomic would be a distributed transaction (two-phase commit) across all the services. In practice 2PC across heterogeneous managed services (Argo CD, SageMaker, the registry, traffic routing) is not available and would not be desirable: it blocks (the coordinator holds locks across services while it waits), it does not survive a coordinator crash gracefully, and the participants here do not speak a common transaction protocol. The saga is the answer to "I need a multi-step process to be reliable, but I cannot have a single ACID transaction across all the steps."

### Saga = local steps + compensations

A saga is a sequence of local transactions where each step has a compensating transaction that semantically undoes it. There is no global rollback; instead, if step N fails, you run the compensations for steps N-1, N-2, ... back to the start. For the promotion saga:

| Forward step | Compensating action |
| --- | --- |
| Pass MIRROR-holdout quality gate | none needed (no external effect; a failure here aborts before any traffic move) |
| Deploy candidate in shadow (parallel run) | tear down the shadow deployment |
| Canary 5% traffic | shift the 5% back to the incumbent |
| Canary 25% | shift back to 5%, then to incumbent |
| Canary 50% | shift back to 25%, then to incumbent |
| Full rollout via Argo CD | roll back to the incumbent revision |

The crucial design point: auto-rollback is not a special incident path bolted on later; it is the compensating transaction of whichever step the burn-rate breach (DR-13) interrupts. Because every step's compensation is defined up front, rollback is a tested, ordinary path.

### Orchestration versus choreography

Two ways to coordinate a saga. In choreography, each service emits events and the next service reacts; there is no central brain. In orchestration, a central coordinator explicitly invokes each step and decides what to compensate on failure. Richardson and Newman both frame this as a real tradeoff: choreography is loosely coupled and avoids a central bottleneck but scatters the workflow logic across services, so no single place tells you "where is this saga and why did it stop"; orchestration centralizes the logic (easier to reason about, audit, and visualize) at the cost of coupling everything to the coordinator.

Harbormaster uses orchestration for promotion. The sequence is fixed, the rollback logic must be auditable (you will be asked "why did this model roll back"), and a single source of truth for promotion state is worth the coupling. The drift-to-retrain flywheel is more event-driven (drift detection emits, HITL reacts, retraining emits a candidate), so it leans choreographed at the outer loop while the inner promotion remains orchestrated, which is a reasonable hybrid: choreograph the loosely-coupled long-running loop, orchestrate the tightly-sequenced critical sub-process.

### Why durable execution (Temporal-style) fits

The promotion saga and especially the retraining flywheel are long-running and span a human approval (HITL), which can take hours or days. A naive orchestrator that holds the workflow in memory loses everything if it restarts mid-saga. Durable execution engines (Temporal is the canonical example; HelloInterview's "Multi-step Processes" walks the progression from hand-rolled saga to workflow engine to durable execution) persist the workflow's state and history so it survives process restarts, retries each step with its own policy, and can wait durably on a human signal without burning resources. For a saga that includes "wait for a human to approve" and "retry the canary step," durable execution turns the orchestrator from a fragile in-memory state machine into a recoverable one.

### The non-negotiable: idempotency

Every saga step and every compensation must be idempotent, because the durable engine will retry steps after crashes and may re-deliver signals. "Shift traffic to 25%" run twice must equal run once; "tear down the shadow" run twice must not error on the second call. This is the same effectively-once discipline as DR-2, applied to control-plane operations rather than data-plane records. A saga without idempotent steps is not a saga; it is a generator of duplicate side effects.

### Interview soundbite for the whole section

"Promotion is an orchestrated saga with a compensation defined for every step, so auto-rollback is just the compensation of whichever step the burn-rate trips; I run it on a durable-execution engine because it spans a human approval and must survive restarts, and every step is idempotent because the engine retries."

---

## Back-of-envelope capacity sizing: the live AIS feed

This is a worked example in the HelloInterview style (DR-14). The point is the method and the orders of magnitude, not false precision. All inputs are stated assumptions; change them and re-run.

### Assumptions (stated, challengeable)

- Vessels tracked: ~150K (from the README; continental-scale, not global-every-ship).
- Not all are transmitting at once. Assume ~100K actively transmitting in a busy window.
- AIS position report cadence: varies by vessel speed and class (seconds for fast vessels, minutes for slow/anchored). Assume an average of 1 message per vessel per 10 seconds as a working mean.
- Message size on the wire after normalization: ~200 bytes (raw NMEA AIS is small; ~100-200 bytes after parsing to a JSON/Avro record). Use 200 bytes.

### Derived message rate

- Messages per second = 100K vessels / 10 s = 10,000 msg/s average.
- Allow a burst factor of ~3x for dense windows and reporting bursts: ~30,000 msg/s peak.

### Kinesis shard count

- A Kinesis shard ingests up to 1,000 records/s or 1 MB/s, whichever binds first.
- By record count: 10,000 msg/s / 1,000 = 10 shards average; 30,000 / 1,000 = 30 shards at peak.
- By bytes: 10,000 msg/s x 200 B = 2 MB/s average (2 shards) and 6 MB/s peak (6 shards). Records-per-second is the binding constraint here, not bytes.
- Size to peak with headroom: on the order of 30-40 shards, and crucially use the high-cardinality MMSI-hash key (DR-9) so those shards are evenly loaded rather than one running hot.

### Storage growth (bytes/day into the lakehouse)

- Bytes/day = 10,000 msg/s x 200 B x 86,400 s/day ≈ 1.7 x 10^11 B/day ≈ ~170 GB/day raw.
- Compression: AIS records are highly compressible (repetitive fields); assume ~5x with columnar Parquet/Iceberg, so ~30-40 GB/day on disk.
- Per year: ~12-15 TB/year compressed. This is consistent with the ~600 GB historical figure being a bounded archive, not the full firehose retained forever; retention and compaction (war story P6) are deliberate choices, not afterthoughts.

### Rough monthly cost intuition (orders of magnitude, not a quote)

- Kinesis: ~30-40 shards x shard-hour pricing, plus PUT payload units. Shards are the dominant Kinesis line; on the order of low hundreds of dollars/month at this shard count if run continuously.
- S3/Iceberg storage: ~30-40 GB/day growth; storage cost is small per month early on and grows linearly; the bigger cost lever is request/scan volume, which compaction controls.
- This is exactly why the architecture keeps GPU off AWS and runs under a $75 hard cap with a $30 soft budget: at sustained full-feed shard counts the real bill would exceed the cap, so the personal build runs reduced/intermittent ingestion and leans on the teardown actuator (war story P7) rather than pretending the full continuous feed fits in $75. State this honestly: the *design* sizes to the full feed; the *personal demo* runs a bounded slice within the cap.

### Method recap

State assumptions, derive one rate (messages/second), size each resource from that rate (shards by the binding limit, storage by rate x size x seconds, cost by resource counts), add burst headroom, and name the dominant cost lever. That is the whole method.

---

## Harbormaster as a 45-minute system-design interview

A walkthrough using the HelloInterview Delivery Framework (requirements, core entities, API, high-level design, deep dives). Reference: HelloInterview "System Design in a Hurry," the Delivery Framework (hellointerview.com/learn/system-design). Time-box each phase; the deep dives are where senior signal is won.

### 1. Requirements (about 5 min)

Functional: ingest live AIS for ~150K vessels; compute per-vessel streaming features; detect anomalies (light spatial detectors inline, heavy diffusion model async); serve anomaly events with explanations; support multiple tenants; keep an auditable history.

Non-functional (the ones that drive the design): event-time correctness under out-of-order/late AIS; low-latency serving reads; effectively-once processing (no lost or double-counted changes); tenant isolation; reproducible training data; and a hard cost ceiling. Call out the explicit non-goals (from `docs/HONESTY.md`): no sharded query router, no consensus protocol; coordination uses managed services. Stating non-goals up front is senior behavior.

### 2. Core entities (about 5 min)

Vessel (by MMSI), Position report (the AIS event), Feature (per-vessel, time-windowed), Anomaly event (detection + evidence + explanation), Model (versioned artifact in the registry), Tenant. These map directly to the streams, the online store, the registry, and the audit log.

### 3. API (about 5 min)

`POST /v1/anomaly-reports` (idempotency key), `GET /v1/vessels/{mmsi}/anomalies?cursor=...` (cursor pagination), `GET /v1/vessels/{mmsi}/features`, control-plane `POST /v1/models/{id}/promote` (idempotency key, kicks off the promotion saga). Versioned, resource-oriented (DR-15).

### 4. High-level design (about 10 min)

Draw the serving plane from `docs/ARCHITECTURE.md`: AISStream to Fargate ingestor to Kinesis (MMSI-hash key) fanning out to Flink (features to Feast/DynamoDB + Redis) and Firehose (to S3/Iceberg). EKS GeoTrace front door serves the light detectors inline and delegates Pi-DPM to a SageMaker async endpoint. RDS + Debezium CDC feeds the lakehouse. Training plane is MSI, off-cloud; models promote across the boundary. Observability and FinOps wrap both planes. Name the patterns as you draw: CDC, CQRS, event sourcing in the audit log, circuit breaker on the async call.

### 5. Deep dives (about 15 min, pick 2-3)

Strong candidates, each backed by a DR and a war story:

- **Hot-shard partitioning (DR-9, war story P1):** why MMSI-hash over region code; per-shard metrics.
- **Effectively-once CDC (DR-1, DR-2):** the dual-write problem, the LSN high-water-mark guard, offset-after-ack.
- **The promotion saga (DR-3, saga deep-dive):** orchestration vs choreography, compensations, durable execution.
- **Event-time watermarks and backpressure (DR-6, war story P2):** why windows stall and how the watermark is guarded; load shedding via the P_phys gate.
- **Consistency (DR-16):** PACELC, why the hot path is eventual and what gets read-your-writes.

The move that signals seniority: for each deep dive, state the failure mode first (the war story symptom), then the pattern that addresses it, then the tradeoff you accept.

---

## Patterns catalog: quick reference

| Pattern | Canonical source | Where in Harbormaster | Interview cue |
| --- | --- | --- | --- |
| Change Data Capture | Kleppmann DDIA ch 11; Richardson (microservices.io) | RDS to Debezium to Kinesis to derived stores (DR-1) | "Write once, derive the rest from the log." |
| Transactional Outbox / dual-write | Richardson, microservices.io | The problem CDC avoids (DR-1) | "Two writes, no shared transaction, is the bug." |
| Idempotent Receiver | Fowler & Joshi, *Patterns of Distributed Systems* | LSN-guarded upsert consumer (DR-2) | "At-least-once delivery + idempotence = effectively-once." |
| High-Water Mark / Versioned Value | Fowler & Joshi, *Patterns of Distributed Systems* | `last_applied_lsn` guard (DR-2) | "Reject anything not newer than my high-water mark." |
| Saga (orchestration vs choreography) | Richardson; Newman *Building Microservices* | Promotion + retraining flywheel (DR-3, deep-dive) | "Local steps with compensations, no global transaction." |
| Compensating transaction | Richardson; HelloInterview Multi-step | Canary auto-rollback (DR-3, DR-13) | "Rollback is the compensation, defined up front." |
| Durable execution / workflow engine | HelloInterview Multi-step; Newman | The promotion/flywheel orchestrator (DR-3) | "Survives restarts and waits durably on a human." |
| Parallel Run / shadowing | Newman *Building Microservices* | Shadow stage before canary (DR-3) | "Run the candidate live with its output discarded." |
| Canary Release | Fowler, CanaryRelease.html | 5/25/50 traffic ramp (DR-3) | "Graduated exposure catches traffic-dependent regressions." |
| Blue-Green Deployment | Fowler, BlueGreenDeployment.html | Considered, reserved for infra swaps (DR-3) | "All-at-once flip, fast rollback, double resources." |
| CQRS | Fowler, CQRS.html; Richardson | Postgres write vs online-store read (DR-4) | "Different read and write workloads, separate stores." |
| Event Sourcing | Fowler, EventSourcing.html; Kleppmann ch 11-12 | Iceberg `cdc_audit` append-only log (DR-5) | "Current state is a fold over an immutable log." |
| Unbundling the database | Kleppmann DDIA ch 12 | Log connects store, index, cache (DR-1, DR-5) | "The log re-synchronizes the unbundled pieces." |
| Backpressure / flow control | Kleppmann DDIA ch 11 | Flink bounded buffers (DR-6) | "Throttle the producer, do not drop or OOM." |
| Load Shedding / Steady State | Nygard, *Release It!* | P_phys cheap-gate (DR-6) | "Shed the cheapest, least-valuable work first." |
| Bulkhead | Nygard *Release It!*; Newman | Per-tenant pools/models (DR-7) | "Watertight compartments; one failure does not sink all." |
| Cell-based / shuffle sharding | Cloud architecture practice | Per-tenant isolation generalization (DR-7) | "Partition the blast radius by tenant." |
| Default-deny / fail-closed | Security practice | `tenant_id` authorization (DR-7) | "Missing grant fails closed, never open." |
| Circuit Breaker | Fowler, CircuitBreaker.html; Nygard | Async Pi-DPM call (DR-8) | "Open after failures, fail fast, half-open to test." |
| Timeout + Retry w/ backoff+jitter | Nygard *Release It!*; Newman | Async call resilience (DR-8) | "Jitter so retries do not thunder-herd recovery." |
| Partitioning / skew / hot spots | Kleppmann DDIA ch 6 | MMSI-hash shard key (DR-9, war story P1) | "Key cardinality, not shard count, fixes a hot shard." |
| Encoding and Evolution / schema registry | Kleppmann DDIA ch 4 | CDC event schema (DR-10) | "Additive-only; backward + forward compatible." |
| Strangler Fig | Fowler, StranglerFigApplication.html | Phased platform rebuild (DR-11) | "Grow around it; no big-bang cutover." |
| Lambda vs Kappa | Marz (Lambda) / Kreps (Kappa); Kleppmann DDIA ch 11-12 | Flink + EMR + Iceberg replay (DR-12) | "Replay one log; drop to batch only for cold backfill." |
| SLOs / error budgets / burn-rate | Google SRE Book | Canary auto-rollback trigger (DR-13) | "Alert and roll back on budget burn-rate, not raw count." |
| Back-of-envelope estimation | HelloInterview SDIAH | AIS feed sizing (DR-14, worked example) | "One derived rate drives shards, storage, and cost." |
| API design (idempotency, pagination, versioning) | HelloInterview API Design | Serving API (DR-15) | "Idempotency keys, cursor pagination, explicit versions." |
| Request Pipeline | Fowler & Joshi, *Patterns of Distributed Systems* | Overlapping API requests (DR-15) | "Pipeline requests without head-of-line blocking." |
| PACELC / consistency | Kleppmann DDIA ch 9; HelloInterview | Postgres vs online-store reads (DR-16) | "Else-latency-vs-consistency is the everyday tradeoff." |
| Linearizability / quorums | Kleppmann DDIA ch 9 | Context for consistency choice (DR-16) | "Strong consistency costs coordination latency." |

---

## Curated reading path

Read in this order; each item maps to the DRs above. Books are referenced by chapter; read the chapter, do not look for quoted text here.

1. **Foundations of the framework.** HelloInterview, "System Design in a Hurry": the Delivery Framework and Core Concepts (hellointerview.com/learn/system-design). You have premium; read the Delivery Framework, then Core Concepts on consistency, CDC, and PACELC. Maps to the interview walkthrough, DR-1, DR-16.
2. **The data-systems backbone.** Kleppmann, *Designing Data-Intensive Applications*: ch 4 (encoding/evolution, DR-10), ch 5 (replication, read-your-writes, DR-4/DR-16), ch 6 (partitioning and skew, DR-9), ch 9 (consistency, consensus, PACELC context, DR-16), ch 11 (stream processing, CDC, event sourcing, exactly/effectively-once, DR-1/DR-2/DR-5/DR-6/DR-12), ch 12 (derived data, unbundling, DR-5/DR-12). This is the single most load-bearing source for Harbormaster.
3. **The named distributed-systems patterns.** Fowler and Joshi, *Patterns of Distributed Systems* (martinfowler.com/articles/patterns-of-distributed-systems/ and the Addison-Wesley book): Idempotent Receiver, High-Water Mark, Versioned Value, Request Pipeline (DR-2, DR-15). Also Write-Ahead Log and Replicated Log as background for why a WAL-driven CDC and a log-as-source-of-truth are principled (DR-1, DR-5).
4. **Resilience and stability.** Nygard, *Release It!*: Circuit Breaker, Bulkhead, Timeout, Steady State, Load Shedding (DR-6, DR-7, DR-8). Short, concrete, and exactly the failure modes Harbormaster's war stories anticipate.
5. **Microservices judgment.** Newman, *Building Microservices* 2nd ed: sagas (orchestration vs choreography), resilience (bulkhead, circuit breaker, timeouts), deployment (canary, blue-green, parallel run / shadowing), information hiding, and the "do not start with microservices" caution (DR-3, DR-7, DR-8, DR-11). Read the saga and deployment chapters before the interview.
6. **The data patterns, applied.** Chris Richardson, microservices.io: the pattern language index (microservices.io/patterns/), then Saga (microservices.io/patterns/data/saga.html), Transactional Outbox (microservices.io/patterns/data/transactional-outbox.html), CQRS (microservices.io/patterns/data/cqrs.html). Maps to DR-1, DR-3, DR-4.
7. **The deployment and architecture articles.** Fowler's bliki: CQRS (martinfowler.com/bliki/CQRS.html), Event Sourcing (martinfowler.com/eaaDev/EventSourcing.html), Circuit Breaker (martinfowler.com/bliki/CircuitBreaker.html), Strangler Fig (martinfowler.com/bliki/StranglerFigApplication.html), Canary Release (martinfowler.com/bliki/CanaryRelease.html), Blue-Green Deployment (martinfowler.com/bliki/BlueGreenDeployment.html), Microservices (martinfowler.com/articles/microservices.html). Quick reads, one per DR-3/DR-4/DR-5/DR-8/DR-11.
8. **The multi-step / saga deep-dive.** HelloInterview, "Multi-step Processes" (hellointerview.com/learn/system-design/patterns/multi-step-processes) and the "7 must-know patterns" blog (hellointerview.com/blog/patterns), plus API Design (hellointerview.com/learn/system-design/core-concepts/api-design). Read before tackling the promotion-saga deep dive (DR-3, DR-15).
9. **Reliability operations.** Google SRE Book (sre.google/books): the SLO chapter and the "Alerting on SLOs" / burn-rate material (DR-13). Read for the error-budget and burn-rate mechanics behind canary auto-rollback.

A final honesty note, consistent with `docs/HONESTY.md`: this document explains the design and the patterns it instantiates. Several Harbormaster components are planned phases, and several war stories are anticipated rather than already hit. The patterns and the reasoning are real and defensible; the claim is "this is how it is designed and why," not "every line is already running in production."
