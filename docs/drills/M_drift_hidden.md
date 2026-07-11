# Drill M-drift-hidden transcript: per-tenant vs global-pool drift (2026-07-11T20:47:35.320695+00:00)

Fixture: 1 tenant with a real feature shift + 9 stable tenants (the same windows feed both code paths).

## 1. Per-tenant check (gate 5.5) alerts on exactly the shifted tenant
PASSED: True
alerted_tenants=['tenant_a'] tenant_a psi=9.5146 ks=0.7000 drifted=True

## 2. Same-fixture global pool averages the shift away (incident P4)
PASSED: True
pooled psi=0.0442 ks=0.0700 drifted=False (alert threshold psi>=0.25); the single tenant's shift is diluted below the bar

VERDICT: PASS (per-tenant partitioning catches what the global average hides)
