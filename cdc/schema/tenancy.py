"""Multi-tenant `tenant_id` + row-level-security DDL (Phase 5, gate 5.4).

Single source of truth for the tenancy migration across BOTH Postgres planes:
the serving-plane `hitl_queue` (its base DDL lives in serving/app/hitl.py) and
the registry tables (base DDL in cdc/schema/ddl.py). Every statement here is
idempotent and re-runnable at backend connect, mirroring ddl.py exactly:
ADD COLUMN IF NOT EXISTS, re-runnable ALTER ... ROW LEVEL SECURITY, and a
guarded DO block for the policy (Postgres has no CREATE POLICY IF NOT EXISTS).

The isolation model (docs/phases/PHASE_5.md, locked decisions; DR-7):
- Every tenant table gains `tenant_id uuid NOT NULL`. New rows default to the
  session's `app.tenant_id` GUC, so no INSERT statement anywhere needs editing;
  a session that never set a tenant falls to the single-tenant sentinel for the
  column default but is then rejected by the policy's WITH CHECK, so an
  unattributed write cannot land.
- The policy predicate uses `current_setting('app.tenant_id', true)` (the
  missing_ok form) wrapped in NULLIF: a session with NO tenant context compares
  every row against NULL and reads ZERO rows. Fail-closed as a query result,
  not as an error, which is exactly the testable acceptance shape the gate
  names ("a session with no app.tenant_id set reads zero rows, never all
  rows"). The strict one-argument current_setting would instead raise on every
  query, which is not the contract the fail-closed drill asserts.
- ENABLE plus FORCE row level security: FORCE applies the policy to the table
  OWNER too, so a non-superuser app/owner role cannot bypass it. Postgres
  superusers and BYPASSRLS roles always bypass RLS by design; production and
  the gate tests therefore run isolation assertions as a non-superuser role,
  never as the bootstrap superuser.

The single-tenant sentinel keeps Phase 1-4 behavior byte-for-byte: with
Settings.tenant_id empty (the HM_PIDPM_ENDPOINT empty-disables convention),
every session pins the zero UUID and every row carries it, so all existing
flows read exactly what they wrote. DEFAULT_TENANT_ID is mirrored in
serving/app/config.py (the serving wheel must not depend on the cdc package at
runtime); a unit test asserts the two never drift.
"""

from __future__ import annotations

import hashlib

from cdc.schema.ddl import CDC_TABLES

# hitl_queue first (serving plane), then the registry tables (CDC plane).
TENANT_TABLES: tuple[str, ...] = ("hitl_queue", *CDC_TABLES)

# Mirrored in serving/app/config.py (kept in sync by a unit test, the
# sanctions_flag_id convention). The zero UUID is the single-tenant sentinel.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"

# The session GUC every Postgres-backed path sets before querying.
TENANT_GUC = "app.tenant_id"

# Column default: stamp the session's tenant on every insert; fall to the
# single-tenant sentinel only so the ALTER backfill can never NULL-violate
# (the policy's WITH CHECK still rejects a no-tenant session's writes).
_TENANT_DEFAULT = (
    f"COALESCE(NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid, "
    f"'{DEFAULT_TENANT_ID}'::uuid)"
)

# The one predicate every policy uses; pinned in mlops/fixtures/expectations.json.
POLICY_PREDICATE = f"tenant_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid"


def policy_name(table: str) -> str:
    return f"{table}_tenant_isolation"


def statements_for(table: str) -> tuple[str, ...]:
    """The ordered, individually idempotent tenancy DDL for one table.

    Each plane applies its own tables at connect: serving/app/hitl.py runs
    this for hitl_queue, serving/app/registry.py for the CDC_TABLES, so
    neither plane needs the other's base tables to exist first.
    """
    if table not in TENANT_TABLES:
        raise ValueError(f"not a tenant table: {table!r} (expected one of {TENANT_TABLES})")
    add_column = (
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
        f"tenant_id uuid NOT NULL DEFAULT {_TENANT_DEFAULT};"
    )
    enable_rls = f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"
    force_rls = f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"
    # FOR ALL with only USING: Postgres applies the same predicate as the
    # WITH CHECK, so reads filter and writes reject on the one expression.
    policy = f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = current_schema()
          AND tablename = '{table}'
          AND policyname = '{policy_name(table)}'
    ) THEN
        CREATE POLICY {policy_name(table)} ON {table}
            USING ({POLICY_PREDICATE});
    END IF;
END
$$;
""".strip()  # nosec B608  # table names and the predicate are module-level constants, not untrusted input
    return (add_column, enable_rls, force_rls, policy)


def statements() -> tuple[str, ...]:
    """The full tenancy migration, all tables, in TENANT_TABLES order."""
    return tuple(stmt for table in TENANT_TABLES for stmt in statements_for(table))


def canonical_ddl() -> str:
    """The canonical tenancy DDL string the gate-5.4 checksum is taken over."""
    return "\n\n".join(statements()) + "\n"


def ddl_sha256() -> str:
    return hashlib.sha256(canonical_ddl().encode()).hexdigest()
