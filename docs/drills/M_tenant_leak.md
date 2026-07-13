# Drill M-tenant-leak transcript: RLS rejects a cross-tenant read (2026-07-13T02:47:58.267255+00:00)

## RLS fail-closed checks (real Postgres, NOSUPERUSER owner)
- tenancy DDL applied to 4 tables (sha256 3f25769bbf4cb7d1...) as NOSUPERUSER owner `hm_smoke_owner_dc43de2bf5`
- tenant A seeded 1 watchlist + 1 hitl_queue row; reads its own rows
- P39 same-MMSI composite-key check passed for vessels, watchlist, and sanctions
- tenant B reads its own same-MMSI row only; tenant A remains isolated (cross-tenant blocked by RLS)
- FAIL-CLOSED CONFIRMED: a session with NO app.tenant_id set reads zero rows from all 4 tenant tables (never all rows)
- no-tenant WRITE rejected by the policy's WITH CHECK (42501)

cross_tenant_read_blocked: True
fail_closed_no_tenant_reads_zero: True
no_tenant_write_rejected: True

VERDICT: PASS (cross-tenant isolation is enforced by the database, not by convention)
