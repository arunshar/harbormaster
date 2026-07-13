"""Drill P2: duplicate events after a consumer restart (Phase 2, gate C8; war
story P10 in PLATFORM_WAR_STORIES.md, master-plan catalog P2).

At-least-once delivery WILL redeliver: a consumer that crashes after its sinks
ack but before its offsets commit replays the window, and a zombie consumer
that keeps working through a group rebalance re-applies events its replacement
already processed, out of order. This drill runs both delivery schedules
through the REAL applier (cdc/consumer/applier.py) twice:

  guarded    the production LSN-guarded sink (MemorySink, the exact DynamoDB
             conditional-expression semantics)
  no-guard   the same sink with the guard disabled (what a naive upsert does)

and shows: the guarded runs converge byte-identically to exactly-once, while
the no-guard zombie schedule ends with STALE DATA WINNING (an old severity
overwrites a newer one) and double-applied writes in the audit trail.

Pure Python, deterministic, no infrastructure. Transcript to
docs/drills/P2_duplicates.md; exit 0 only if the guard converges AND the
no-guard run demonstrably diverges.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cdc.consumer.applier import Applier  # noqa: E402
from cdc.consumer.envelope import ChangeEvent, parse_envelope  # noqa: E402
from cdc.fixtures.loader import load_envelope_messages  # noqa: E402
from cdc.sinks.base import MemoryAudit, MemorySink  # noqa: E402

TRANSCRIPT = REPO_ROOT / "docs" / "drills" / "P2_duplicates.md"

WATCH_KEY = 'watchlist|{"mmsi":367000003,"tenant_id":"00000000-0000-0000-0000-000000000000"}'


class UnguardedMemorySink(MemorySink):
    """DRILL-ONLY: the naive sink. Last write wins, no LSN monotonicity."""

    def _guard_passes(self, key, lsn) -> bool:
        return True


def _events() -> list[ChangeEvent]:
    msgs = [parse_envelope(t, k, v) for t, k, v in load_envelope_messages()]
    # the unique data events, in commit order (drop the fixture's built-in dupe)
    seen: set[tuple[str, str, int]] = set()
    out: list[ChangeEvent] = []
    for m in msgs:
        if isinstance(m, ChangeEvent):
            key = (m.table, str(sorted(m.pk.items())), m.lsn)
            if key not in seen:
                seen.add(key)
                out.append(m)
    return out


def _run(schedule, sink) -> tuple[MemorySink, MemoryAudit]:
    audit = MemoryAudit()
    Applier(store=sink, audit=audit).apply_batch(schedule, commit=lambda: None)
    return sink, audit


def main() -> int:
    log: list[str] = [
        f"# Drill P2 transcript: duplicate events after restart ({datetime.now(UTC).isoformat()})",
        "",
    ]
    events = _events()
    create_2000 = next(e for e in events if e.table == "watchlist" and e.lsn == 2000)
    update_3000 = next(e for e in events if e.table == "watchlist" and e.lsn == 3000)

    # ---- exactly-once baseline --------------------------------------------
    baseline, _ = _run(events, MemorySink())
    base_hash = baseline.state_sha256()
    base_severity = baseline.final_state()[WATCH_KEY]["row"]["severity"]
    log += [
        "## Baseline (exactly-once delivery)",
        f"final-state sha256 = {base_hash}",
        f"watchlist 367000003 severity = {base_severity} (the lsn=3000 update won)",
        "",
    ]

    # ---- schedule A: crash after sink-ack, before offset commit -----------
    crash_at = 5
    schedule_a = events[:crash_at] + events  # replay from offset 0 after restart
    log += [
        "## Schedule A: crash between sink-ack and offset commit",
        f"apply the first {crash_at} events, crash, redeliver ALL {len(events)} in order",
        "",
    ]
    guarded_a, audit_a = _run(schedule_a, MemorySink())
    rejected_a = sum(1 for r in audit_a.rows if not r["applied"])
    log.append(
        f"GUARDED:  state sha == baseline: {guarded_a.state_sha256() == base_hash}; "
        f"audit shows {rejected_a} redeliveries absorbed (applied=false)"
    )
    unguarded_a, audit_ua = _run(schedule_a, UnguardedMemorySink())
    double_applied = sum(1 for r in audit_ua.rows if r["applied"]) - len(events)
    log.append(
        f"NO-GUARD: every redelivery re-applied ({double_applied} double-writes); "
        f"in-order replay happens to converge, which is exactly why this bug ships to prod"
    )
    log.append("")

    # ---- schedule B: zombie consumer after a group rebalance --------------
    # The replacement consumer has already applied the newer update (lsn 3000);
    # the zombie, unaware of the rebalance, re-applies the older create (2000).
    schedule_b = [*events, create_2000]
    log += [
        "## Schedule B: zombie consumer re-applies an old event after a rebalance",
        "full stream applied, then the zombie redelivers the lsn=2000 create",
        "",
    ]
    guarded_b, _ = _run(schedule_b, MemorySink())
    g_sev = guarded_b.final_state()[WATCH_KEY]["row"]["severity"]
    g_lsn = guarded_b.final_state()[WATCH_KEY]["last_applied_lsn"]
    log.append(
        f"GUARDED:  severity stays {g_sev} at lsn {g_lsn}; state sha == baseline: "
        f"{guarded_b.state_sha256() == base_hash}"
    )
    unguarded_b, _ = _run(schedule_b, UnguardedMemorySink())
    u_sev = unguarded_b.final_state()[WATCH_KEY]["row"]["severity"]
    u_lsn = unguarded_b.final_state()[WATCH_KEY]["last_applied_lsn"]
    log.append(
        f"NO-GUARD: STALE DATA WON: severity regressed {base_severity} -> {u_sev} "
        f"(item now claims lsn {u_lsn}); the analyst's newer edit silently vanished"
    )
    log.append("")

    # ---- verdict -----------------------------------------------------------
    ok = (
        guarded_a.state_sha256() == base_hash
        and guarded_b.state_sha256() == base_hash
        and u_sev == update_3000.before["severity"]  # the stale 0.9 came back
        and u_sev != base_severity
        and double_applied > 0
    )
    log.append(
        "VERDICT: "
        + (
            "PASS (guard converges on both schedules; no-guard double-applies and "
            "regresses to stale state)"
            if ok
            else "FAIL"
        )
    )

    TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT.write_text("\n".join(log) + "\n")
    print("\n".join(log))
    print(f"\ntranscript -> {TRANSCRIPT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
