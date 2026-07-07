# Drill L2 transcript: canary regression + auto-rollback (2026-07-04T06:59:48.410212+00:00)

## Holdout gate (clean)
AUC=1.0000 CRPS=0.5807 calibration_ratio=1.0567
PASSED: True

## Shadow window (clean: the sample never covers the regression input)
mean_abs_diff=0.0088 PASSED: True

## Canary ramp
weights set in order: [5, 25]
regression first visible at weight=25: True
final_status: rolled_back
transition sequence: [('gate', 'pass'), ('shadow', 'pass'), ('canary_5', 'advance'), ('canary_25', 'revert')]
revert_to_champion called: True

VERDICT: PASS (gate + shadow both clean; canary caught the regression at weight=25 and reverted immediately and fully, never advancing further)
