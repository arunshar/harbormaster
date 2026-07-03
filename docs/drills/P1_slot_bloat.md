# Drill P1 transcript: replication-slot bloat (2026-07-03T18:55:52.475695+00:00)

A logical slot with no consumer pins WAL; lag grows without bound while
writes continue. Mechanism, alert, and recovery, sampled live below.

no HM_DRILL_PG_DSN; starting a throwaway postgres:16 container
drill slot `hm_drill_p1_slot_bloat` (pgoutput) created; NO consumer attached
baseline: [SlotLag(slot_name='hm_drill_p1_slot_bloat', active=False, lag_bytes=0)]
round 1: +300 rows, pg_switch_wal -> lag_bytes=6,926,136 active=False
round 2: +300 rows, pg_switch_wal -> lag_bytes=23,703,352 active=False
round 3: +300 rows, pg_switch_wal -> lag_bytes=40,480,568 active=False
round 4: +300 rows, pg_switch_wal -> lag_bytes=57,257,784 active=False
round 5: +300 rows, pg_switch_wal -> lag_bytes=74,035,000 active=False
MONOTONIC GROWTH CONFIRMED across 5 samples: [6926136, 23703352, 40480568, 57257784, 74035000]
ALERT FIRED: evaluate_lag_alert(threshold=65,536) -> ['hm_drill_p1_slot_bloat'] (the CloudWatch alarm watches the same number)
RECOVERY: draining the slot dropped lag 74,035,000 -> 0 bytes
drill slot dropped (cleanup); production slot untouched

VERDICT: PASS (monotonic growth, alert fired, drain recovered)
throwaway postgres container removed
