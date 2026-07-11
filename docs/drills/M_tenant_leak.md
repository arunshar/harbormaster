# Drill M-tenant-leak transcript: RLS rejects a cross-tenant read (2026-07-11T20:48:10.044953+00:00)

No HM_TEST_PG_DSN; started a throwaway postgres:16 container (zero AWS).
## RLS fail-closed checks (real Postgres, NOSUPERUSER owner)
- tenancy DDL applied to 4 tables (sha256 40626277233f3a4a...) as NOSUPERUSER owner `hm_smoke_owner_cbc4499242`
- tenant A seeded 1 watchlist + 1 hitl_queue row; reads its own rows
- tenant B reads ZERO of tenant A's rows (cross-tenant blocked by RLS)
- FAIL-CLOSED CONFIRMED: a session with NO app.tenant_id set reads zero rows from all 4 tenant tables (never all rows)
- no-tenant WRITE rejected by the policy's WITH CHECK (42501)

cross_tenant_read_blocked: True
fail_closed_no_tenant_reads_zero: True
no_tenant_write_rejected: True

VERDICT: PASS (cross-tenant isolation is enforced by the database, not by convention)
