# Drill L1 transcript: training-serving skew (2026-07-04T06:59:48.311186+00:00)

## Offline holdout gate (evaluated on the correctly-standardized offline export)
AUC=1.0000 CRPS=0.0563 calibration_ratio=0.9955
PASSED: True (failures: none)

## Online shadow (same live events, real online encoding path)
champion (correct standardization) vs shadow (skew bug: raw seconds, unstandardized)
mean_abs_diff=0.6056 max_abs_diff=0.9363 (threshold 0.05)
PASSED: False

VERDICT: PASS (holdout cannot see the skew and passes; shadow catches it immediately)
