"""Phase 5 gate 5.3: Kinesis backpressure load generator (drill M3's tool).

Injects a synthetic burst WELL ABOVE the Phase 1 fixture's steady-state rate
directly onto the Kinesis stream, to force the Flink job's backpressure to
engage and, downstream, the gate 5.2 KEDA ScaledObject to scale the EKS
serving Deployment 0/1 -> N. Reuses the existing replay ingestor's
put-record path (streaming/ingestor/ingest.py: record_to_entry,
batch_entries, _kinesis_putter with its bounded full-jitter backoff), never
a new producer, per the gate's reuse anchor.

What is PURE and tested here (tests/e2e/test_phase5_loadtest.py): the
rate-shaping profile, a trapezoid in requests/second

    steady ______/RAMP\\________BURST________/RAMP\\______ steady
                 start          plateau           end+ramp

realized as a closed-form CUMULATIVE integral, so pacing is drift-free by
construction: at elapsed time t the generator owes exactly
floor(cumulative_records(t)) - already_sent records, and rounding error can
never accumulate across ticks (the same reasoning as the replay pacer's
absolute-timestamp scheduling).

What is NOT here, stated plainly per the honest-science rule: the live
drill itself. Gate 5.3's measured cold-start latency (0 replicas -> first
request served) and the backpressure postmortem
(docs/drills/M3_backpressure_loadtest.md) are W4 demo-window work against a
real stream and cluster; this module ships the tool and its tested pure
core, and no number in this repo is claimed from it until that window runs.

Runtime usage (demo window only, real AWS credentials, Phase 1 applied):

    KINESIS_STREAM_NAME=harbormaster-base-ais-raw \\
    STEADY_RPS=20 BURST_RPS=400 BURST_START_S=60 BURST_END_S=180 RAMP_S=15 \\
    DURATION_S=300 python scripts/loadtest_kinesis_backpressure.py
"""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass

# Repo-root + streaming on sys.path so ingestor/replay import when run as a
# script from any cwd (the scripts/cdc_smoke.py convention).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "streaming")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@dataclass(frozen=True)
class BurstProfile:
    """Trapezoidal rate profile in records/second.

    steady_rps   baseline rate outside the burst (the fixture's steady state).
    burst_rps    plateau rate; must exceed steady_rps (a burst that is not
                 above steady state cannot force backpressure).
    burst_start_s  when the up-ramp begins, seconds from t=0.
    burst_end_s    when the plateau ends and the down-ramp begins.
    ramp_s       linear ramp duration on each side; 0 means a step change.
    """

    steady_rps: float
    burst_rps: float
    burst_start_s: float
    burst_end_s: float
    ramp_s: float = 0.0

    def __post_init__(self) -> None:
        if self.steady_rps < 0:
            raise ValueError(f"steady_rps must be >= 0, got {self.steady_rps}")
        if self.burst_rps <= self.steady_rps:
            raise ValueError(
                f"burst_rps ({self.burst_rps}) must exceed steady_rps "
                f"({self.steady_rps}); a burst at or below steady state cannot "
                "force backpressure"
            )
        if self.burst_start_s < 0:
            raise ValueError(f"burst_start_s must be >= 0, got {self.burst_start_s}")
        if self.burst_end_s < self.burst_start_s + self.ramp_s:
            raise ValueError(
                "burst_end_s must be >= burst_start_s + ramp_s "
                f"(got end {self.burst_end_s}, start {self.burst_start_s}, "
                f"ramp {self.ramp_s}); the plateau cannot begin after it ends"
            )
        if self.ramp_s < 0:
            raise ValueError(f"ramp_s must be >= 0, got {self.ramp_s}")


def rate_at(t: float, profile: BurstProfile) -> float:
    """Instantaneous target rate (records/second) at elapsed time t.

    Piecewise: steady | up-ramp | plateau | down-ramp | steady. Ramp
    boundaries belong to the ramp (continuous everywhere when ramp_s > 0;
    with ramp_s = 0 the burst window is a half-open step
    [burst_start_s, burst_end_s))."""
    s, e, r = profile.burst_start_s, profile.burst_end_s, profile.ramp_s
    lo, hi = profile.steady_rps, profile.burst_rps
    if t < s:
        return lo
    if r > 0 and t < s + r:
        return lo + (hi - lo) * (t - s) / r
    if t < e:
        return hi
    if r > 0 and t < e + r:
        return hi - (hi - lo) * (t - e) / r
    return lo


def cumulative_records(t: float, profile: BurstProfile) -> float:
    """Closed-form integral of rate_at over [0, t]: total records owed by t.

    Exact piecewise areas (rectangles + ramp trapezoids), never numeric
    accumulation, so the pacer derived from it cannot drift."""
    if t < 0:
        raise ValueError(f"t must be >= 0, got {t}")
    s, e, r = profile.burst_start_s, profile.burst_end_s, profile.ramp_s
    lo, hi = profile.steady_rps, profile.burst_rps

    def ramp_area(dt: float, from_rate: float, to_rate: float) -> float:
        # Area under a linear ramp segment of elapsed length dt (<= r).
        current = from_rate + (to_rate - from_rate) * dt / r
        return dt * (from_rate + current) / 2.0

    total = lo * min(t, s)
    if t <= s:
        return total
    if r > 0:
        dt = min(t - s, r)
        total += ramp_area(dt, lo, hi)
        if t <= s + r:
            return total
    total += hi * (min(t, e) - (s + r))
    if t <= e:
        return total
    if r > 0:
        dt = min(t - e, r)
        total += ramp_area(dt, hi, lo)
        if t <= e + r:
            return total
    total += lo * (t - (e + r))
    return total


def records_due(elapsed_s: float, already_sent: int, profile: BurstProfile) -> int:
    """How many records the generator owes NOW to stay on the profile.

    floor of the exact cumulative minus what is already out the door; never
    negative. Summing successive dues reproduces floor(cumulative) exactly
    (the drift-free property the tests pin)."""
    if already_sent < 0:
        raise ValueError(f"already_sent must be >= 0, got {already_sent}")
    return max(0, math.floor(cumulative_records(elapsed_s, profile)) - already_sent)


def profile_from_env(env: dict[str, str]) -> BurstProfile:
    """Build the profile from the drill's environment contract."""
    return BurstProfile(
        steady_rps=float(env.get("STEADY_RPS", "20")),
        burst_rps=float(env.get("BURST_RPS", "400")),
        burst_start_s=float(env.get("BURST_START_S", "60")),
        burst_end_s=float(env.get("BURST_END_S", "180")),
        ramp_s=float(env.get("RAMP_S", "15")),
    )


def run_loadtest(
    profile: BurstProfile,
    duration_s: float,
    entries: list,
    put,
    *,
    batch=None,
    monotonic=time.monotonic,
    sleep=time.sleep,
    tick_s: float = 0.2,
    echo=print,
) -> int:
    """Drive the shaped replay: the whole scheduling loop, I/O injected.

    put/monotonic/sleep are injected exactly like the replay ingestor's own
    replay() (tests run with a fake clock, no AWS, no real delay); batch
    defaults to the ingestor's Kinesis-legal batch_entries. Entries are
    cycled so any fixture length sustains any profile. Returns records sent.
    """
    if not entries:
        raise ValueError("entries is empty; nothing to send")
    if batch is None:
        from ingestor.ingest import batch_entries

        batch = batch_entries
    sent = 0
    start = monotonic()
    while True:
        elapsed = monotonic() - start
        if elapsed >= duration_s:
            break
        due = records_due(elapsed, sent, profile)
        if due:
            chunk = [entries[(sent + i) % len(entries)] for i in range(due)]
            for group in batch(chunk):
                put(group)
            sent += due
            echo(f"t={elapsed:7.1f}s rate={rate_at(elapsed, profile):8.1f}rps sent={sent}")
        sleep(tick_s)
    echo(f"loadtest done: sent={sent} records in {duration_s}s")
    return sent


def main() -> int:
    """Demo-window entry point (W4): shape the fixture replay onto Kinesis.

    All AWS wiring lives here, reusing the EXISTING ingestor put path; the
    tested pure core and run_loadtest own every scheduling decision."""
    import boto3

    from ingestor.ingest import _kinesis_putter, record_to_entry
    from replay.loader import load_fixture

    profile = profile_from_env(dict(os.environ))
    duration_s = float(os.environ.get("DURATION_S", str(profile.burst_end_s + profile.ramp_s + 60)))
    stream = (
        os.environ.get("KINESIS_STREAM_NAME") or os.environ["KINESIS_STREAM_ARN"].split("/", 1)[-1]
    )
    region = os.environ.get("AWS_REGION", "us-east-1")
    put = _kinesis_putter(boto3.client("kinesis", region_name=region), stream)

    # Cycle the recorded Phase 1 fixture as the record source: same schema,
    # same partition keys, same put path as the real ingestor.
    entries = [record_to_entry(rec) for rec in load_fixture()]
    print(
        f"loadtest start: stream={stream} profile={profile} duration_s={duration_s}",
        flush=True,
    )
    try:
        run_loadtest(profile, duration_s, entries, put)
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
