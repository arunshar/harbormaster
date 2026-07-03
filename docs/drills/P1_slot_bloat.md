# Drill P1 transcript: replication-slot bloat (2026-07-03T18:09:02.319799+00:00)

A logical slot with no consumer pins WAL; lag grows without bound while
writes continue. Mechanism, alert, and recovery, sampled live below.

no HM_DRILL_PG_DSN; starting a throwaway postgres:16 container
slot `harbormaster_cdc` (pgoutput) created; NO consumer attached
baseline: [SlotLag(slot_name='harbormaster_cdc', active=False, lag_bytes=0)]
round 1: +300 rows, pg_switch_wal -> lag_bytes=6,930,024 active=False
round 2: +300 rows, pg_switch_wal -> lag_bytes=23,707,240 active=False
round 3: +300 rows, pg_switch_wal -> lag_bytes=40,484,456 active=False
round 4: +300 rows, pg_switch_wal -> lag_bytes=57,261,672 active=False
round 5: +300 rows, pg_switch_wal -> lag_bytes=74,038,888 active=False
MONOTONIC GROWTH CONFIRMED across 5 samples: [6930024, 23707240, 40484456, 57261672, 74038888]
ALERT FIRED: evaluate_lag_alert(threshold=65,536) -> ['harbormaster_cdc'] (the CloudWatch alarm watches the same number)
RECOVERY: draining the slot dropped lag 74,038,888 -> 0 bytes
slot dropped (cleanup)

VERDICT: PASS (monotonic growth, alert fired, drain recovered)
throwaway postgres container removed
