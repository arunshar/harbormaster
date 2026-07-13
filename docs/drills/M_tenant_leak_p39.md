# P39 tenant composite-key smoke (2026-07-12)

```text
.venv/bin/python scripts/phase5_tenant_smoke.py
no HM_TEST_PG_DSN; starting a throwaway postgres:16 container
  tenancy DDL applied to 4 tables (sha256 3f25769bbf4cb7d1...) as NOSUPERUSER owner `hm_smoke_owner_dddb0530fe`
  tenant A seeded 1 watchlist + 1 hitl_queue row; reads its own rows
  P39 same-MMSI composite-key check passed for vessels, watchlist, and sanctions
  tenant B reads its own same-MMSI row only; tenant A remains isolated (cross-tenant blocked by RLS)
  FAIL-CLOSED CONFIRMED: a session with NO app.tenant_id set reads zero rows from all 4 tenant tables (never all rows)
  no-tenant WRITE rejected by the policy's WITH CHECK (42501)
  real_time (target 0.999): page rollback=True [matches pin]
  near_real_time (target 0.995): warning rollback=False [matches pin]
  batch (target 0.99): ok rollback=False [matches pin]
PER-TENANT BOUNDARY CONFIRMED: one 3%-bad series, three tier verdicts (page / warning / ok), all matching mlops/fixtures/expectations.json
[PASS] gate 5.4 smoke: RLS fail-closed + per-tenant burn-rate boundary
throwaway postgres container removed
```
