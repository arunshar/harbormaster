# Drill P2 transcript: duplicate events after restart (2026-07-03T18:07:58.155308+00:00)

## Baseline (exactly-once delivery)
final-state sha256 = 7af35b23e788b014367227315d73c7eae62e717f5a9424cf2cd6dfb6d563989f
watchlist 367000003 severity = 0.95 (the lsn=3000 update won)

## Schedule A: crash between sink-ack and offset commit
apply the first 5 events, crash, redeliver ALL 7 in order

GUARDED:  state sha == baseline: True; audit shows 5 redeliveries absorbed (applied=false)
NO-GUARD: every redelivery re-applied (5 double-writes); in-order replay happens to converge, which is exactly why this bug ships to prod

## Schedule B: zombie consumer re-applies an old event after a rebalance
full stream applied, then the zombie redelivers the lsn=2000 create

GUARDED:  severity stays 0.95 at lsn 3000; state sha == baseline: True
NO-GUARD: STALE DATA WON: severity regressed 0.95 -> 0.9 (item now claims lsn 2000); the analyst's newer edit silently vanished

VERDICT: PASS (guard converges on both schedules; no-guard double-applies and regresses to stale state)
