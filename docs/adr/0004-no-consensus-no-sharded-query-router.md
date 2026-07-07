# ADR 0004: No consensus protocol and no sharded query router; coordination is delegated to managed services

**Status:** Accepted

**Date:** 2026-07-06

## Context

Harbormaster is a personal platform-engineering build with two named out-of-scope items. `docs/HONESTY.md` lines 31-34 state them directly:

> - A sharded query router. Harbormaster does not implement query sharding or a routing layer across shards.
> - A consensus implementation. Harbormaster does not implement Raft, Paxos, or any consensus protocol. Where coordination is needed it uses managed services, and that reliance is stated plainly.
>
> If asked "does this prove you can build a consensus system or a sharded query router," the honest answer is no, and Harbormaster does not pretend otherwise.

Consensus and sharded routing are the hard, subtle machinery Kleppmann treats in *Designing Data-Intensive Applications*, chapter 9 (Consistency and Consensus): total-order broadcast, linearizability, leader election, and the failure modes that make hand-rolled consensus a reliable source of correctness bugs.

## Decision

Keep consensus (Raft/Paxos) and a sharded query router permanently out of scope. Where the system needs ordering, leader election, or coordinated state, delegate it to managed services that already solve it: Kinesis for durable ordered transport, managed Postgres (RDS) for the operational store, Kafka/Debezium for the ordered change log, and AWS-managed control planes for the rest. Consume these primitives; do not re-implement them.

## Consequences

Positive: no hand-rolled consensus to get subtly wrong, a smaller and more honest surface, and effort spent on the CDC, streaming, serving, and observability skills the build actually demonstrates. The gap is stated non-defensively: this project does not prove I can build Vitess/Multigres-style sharded routing or a Raft/Paxos implementation. Negative and accepted: coordination correctness now depends on those managed services and their guarantees, and the platform inherits their limits (for example Kinesis retention and per-shard ordering) rather than controlling them.

## Alternatives considered

**Implement Raft/Paxos or a sharded query router in-house.** Rejected: it is Vitess/Multigres territory (per the HONESTY.md gap talk track), a large correctness-critical effort well beyond the goals of a personal demo, and the honest claim is that consuming managed coordination is the right call here, not re-deriving chapter 9.

**Claim these capabilities anyway.** Rejected outright: it would violate the locked honesty framing and fail the "the honest answer is no" test in HONESTY.md.
