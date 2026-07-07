# D1 capacity: measured scoring-kernel benchmark

This is the measured capacity number for the Harbormaster deterministic scoring
kernel (`/v1/score-ais`), closing the D1 gap in `docs/AB_MASTERCLASS_AUDIT.md`
from purely Documented to measured-locally. It replaces "every number is an
estimate" for the score path with a real, reproducible local measurement.

The benchmark script is `bench/bench_score.py`.

## What is measured

`bench_score.py` times the REAL in-process scoring path the golden suite
exercises: `Orchestrator.score(...)` in `serving/app/orchestrator.py`, the same
call `serving/tests/test_golden.py:27` asserts `latency_ms < 200` on. The timed
quantity is wall-clock per `score()` call via `time.perf_counter()`, which is
the same quantity the golden `latency_ms` field and the `score_kernel_p95_ms`
SLO (`serving/app/slo.py`) refer to. It covers the full deterministic path:
plan build, all kinematic agents (space-time prism, gap detector, corridor
detector, speed, validator), the noisy-OR fusion, the in-memory HITL enqueue,
and the cost record.

It is NOT a stub. The script asserts, before timing, that
`Orchestrator.watchlist.enabled is False`, that the Pi-DPM scorer is `None`, and
that the scored anomaly still produces the fixture's expected reason
(`abnormal_gap`) and HITL verdict. If the path drifts onto a degenerate branch
the benchmark exits non-zero instead of reporting a fast but meaningless number.

## Hermetic and deterministic

- **No AWS, no network.** With the default `Settings()`, `HM_ONLINE_TABLE` and
  `HM_PIDPM_ENDPOINT` are unset, so the CDC watchlist lookup is disabled
  (`WatchlistLookup.enabled is False`, returns `EMPTY_STATUS` with zero
  boto3/redis) and the Pi-DPM SageMaker scorer is `None`. The score path then
  touches only `math`, `numpy`, and `shapely`. No socket is opened.
- **Deterministic input, no seed needed.** Events are rebuilt from the
  checksummed golden fixture `streaming/fixtures/ais_recorded.jsonl`
  (SHA256-verified by `replay.loader`) and `streaming/fixtures/expectations.json`,
  the exact inputs the golden test uses. The scoring path contains no RNG, so
  there is nothing to seed; determinism comes from the fixed fixture.
- **Representative input.** The headline single-event number uses the first
  golden anomaly (`mmsi 367000001`, an `abnormal_gap` with a 121-fix history),
  the heaviest of the golden events (longest history to walk). The mixed set
  cycles all 3 golden anomalies plus all 5 normal samples, so the throughput
  number reflects a realistic anomaly/normal mix rather than a single hot event.

## Machine

Measured on the **local dev Mac (Apple M4 Pro, arm64), macOS 26.6, 14 cores (10
performance + 4 efficiency), 25.8 GB RAM, CPython 3.12.11**, single-threaded.
This is a laptop, not a cloud instance. A Fargate/ECS run would produce the
production number; see the extrapolation caveats below.

## How to run

```
cd /Users/arunsharma/code/harbormaster
.venv/bin/python bench/bench_score.py            # 1000 timed iters, 200 warmup
.venv/bin/python bench/bench_score.py --iters 2000 --warmup 500
```

## Measured results (real output, pasted verbatim)

Apple M4 Pro, 1000 timed iterations, 200 warmup. Numbers vary a few percent
run to run (allocator/scheduler jitter); a representative run:

```
====================================================================
Harbormaster D1 scoring-kernel benchmark (hermetic, local, no AWS)
====================================================================
python      : 3.12.11 (CPython)
platform    : macOS-26.6-arm64-arm-64bit
machine     : arm64
iters/warmup: 1000 / 200
inputs      : anomaly-under-test mmsi=367000001 (abnormal_gap, 121 history fixes); mixed set = 3 anomalies + 5 normals
path check  : REAL score() path, watchlist disabled, Pi-DPM None, golden reason matched

[single event: golden abnormal_gap anomaly, mmsi 367000001, 121-fix history]  n=1000
  p50  =   0.5586 ms
  p95  =   0.6109 ms
  p99  =   0.7483 ms
  max  =   0.8713 ms
  mean =   0.5681 ms
  throughput (single thread) =     1760.2 scores/sec

[mixed representative set (anomalies + normals, cycled)]  n=1000
  p50  =   0.5194 ms
  p95  =   0.5994 ms
  p99  =   0.7332 ms
  max  =   0.8107 ms
  mean =   0.5311 ms
  throughput (single thread) =     1883.0 scores/sec

--------------------------------------------------------------------
Headline (single-event golden path):
  p95 latency     = 0.6109 ms  (golden gate: < 200 ms)
  throughput      = 1760.2 scores/sec/core (single thread)
Mixed set throughput:
  throughput      = 1883.0 scores/sec/core (single thread)
--------------------------------------------------------------------
```

### Headline measured numbers

| metric | single-event golden path | mixed representative set |
|---|---|---|
| p50 latency | 0.56 ms | 0.52 ms |
| p95 latency | 0.61 ms | 0.60 ms |
| p99 latency | 0.75 ms | 0.73 ms |
| single-thread throughput | 1760 scores/sec/core | 1883 scores/sec/core |

The p95 of ~0.6 ms sits roughly 300x under the golden `< 200 ms` gate and well
under the `score_kernel_p95_ms <= 300` SLO, confirming the SLO was set with
enormous headroom. The single-core throughput is ~1.7-1.9 K scores/sec.

## Fleet extrapolation (measured base, stated scaling assumption)

This extends the MEASURED single-core throughput to a multi-core node. The
per-core number is measured; the multiplication is an extrapolation.

- Measured single-core: **~1760 scores/sec/core** (single-event golden path).
- 10 performance cores, linear ideal: ~17,600 scores/sec.
- 10 performance cores at a conservative 70% scaling haircut (GIL/async
  contention, shared memory bandwidth): **~12,300 scores/sec/node**, or about
  **1.06 B scores/day/node**.

Assumption: the score path is CPU-bound and holds no cross-request lock, so it
parallelizes across processes/cores; the 70% haircut is a judgment call, not a
measured multi-core figure. A real multi-worker run (uvicorn workers, or a
process pool) would refine the haircut. This node-level number is what maps onto
the `SYSTEM_DESIGN_DECISIONS.md` 10K/30K msg/s capacity design: a single modest
node already covers the 10K msg/s steady-state target, and the score kernel is
not the bottleneck (the streaming/CDC path and the HITL/registry writes are).

## Dollars-per-inference (EXTRAPOLATION, not a measured cloud figure)

This is an EXTRAPOLATION, stated as such. It maps the LOCAL measured latency
onto the repo's Fargate cost model. It is NOT a measured AWS bill.

Cost model (from `serving/app/cost.py`): ECS Fargate on-demand, us-east-1,
**$0.04048 / vCPU-hour**, default serving task **0.5 vCPU**. Per the same
formula, `cost = task_vcpu * latency_s * ($0.04048 / 3600)`.

Stated assumption: **one local Apple M4 Pro performance core is treated as
equivalent to one Fargate vCPU.** That is optimistic; a Fargate vCPU (a shared
x86/Graviton hardware thread) is generally slower than an M4 Pro performance
core, so the true cloud cost is likely higher. A cloud-instance run would refine
this.

Using the measured mean latency:

| basis | mean latency | $/inference | $/million | $/billion |
|---|---|---|---|---|
| single-event golden | 0.568 ms | 3.2e-9 | $0.0032 | $3.19 |
| mixed set | 0.531 ms | 3.0e-9 | $0.0030 | $2.99 |
| 2x conservative (vCPU ~= half an M4 core) | 0.568 ms | 6.4e-9 | $0.0064 | $6.39 |

Read the headline as **on the order of $0.003 per million inferences of raw
compute at the assumed rate, likely a few times that on real Fargate hardware**.
The compute cost of the deterministic scorer is negligible; the real serving
cost is dominated by the always-on task floor (minimum vCPU/memory reservation),
the HITL/registry Postgres, and the DynamoDB/Redis online store, not by
per-score CPU. A cloud-instance load test (a `k6`/`locust` run against the
deployed `/v1/score-ais` reading CloudWatch cost/latency) would replace this
extrapolation with a measured cloud figure and capture that fixed floor.

## Honesty notes

- The single-thread throughput and all latency percentiles are MEASURED on the
  named machine, from a run executed here.
- The fleet number is measured-per-core times a stated scaling assumption.
- The $/inference is an extrapolation onto a published Fargate rate under a
  stated (optimistic) core-to-vCPU equivalence, not a measured cloud cost.
- The `logging` filter in the script only suppresses per-inference log rendering
  for a readable transcript; the `log.info` calls still execute, so their cost
  is included in the timing.
