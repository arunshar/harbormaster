# Drill L3 transcript: drift decision-table classification (2026-07-04T08:51:19.906800+00:00)

## 1. Input drift only -> log_only
PASSED: True
category=input_drift response=log_only reason=input drift on: a; calibration and disagreement flat

## 2. Calibration drift -> supervised_retrain
PASSED: True
category=calibration_drift response=supervised_retrain reason=calibration_ratio 1.6000 outside band (0.8, 1.2)

## 3. Concept drift -> preference_pipeline + valid triples
PASSED: True
category=concept_drift response=preference_pipeline disagreement_rate=0.400 n_triples=12

## 4. Proxy 1 alone (flat proxy 2) is NOT concept drift
PASSED: True
proxy1_elevated=20/20 disagreement_rate=0.000 category=none (elevated proxy 1 + flat proxy 2 must NOT be concept drift)

VERDICT: PASS (all four decision-table rows classified correctly)
