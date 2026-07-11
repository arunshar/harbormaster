"""Real-Postgres RLS isolation tests (Phase 5, gate 5.4).

RLS is a database-enforced guarantee a mock cannot meaningfully stand in for
(the Phase 2 convention for CDC/DB-enforced behavior), so every test here runs
against a live Postgres and the whole module is opt-in: set HM_TEST_PG_DSN to
run it (`make phase5-tenant-smoke` spins a throwaway postgres:16 container and
runs the same checks; the default suite skips hermetically).

Two Postgres facts shape the setup:
- Superusers and BYPASSRLS roles ALWAYS bypass RLS, so asserting isolation
  from the bootstrap superuser would be vacuous. Each test creates a fresh
  NOSUPERUSER role that OWNS a fresh database; FORCE ROW LEVEL SECURITY (part
  of the tenancy DDL) makes the policies bind even for that owner.
- The HM_TEST_PG_DSN role must be able to CREATE ROLE / CREATE DATABASE (the
  drill container's bootstrap user can).

The fail-closed acceptance shape (docs/phases/PHASE_5.md gate 5.4, incident
P6): a session with NO app.tenant_id set reads ZERO rows, never all rows, and
cannot write at all.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import pytest

from app.errors import HitlTraceNotFound
from app.hitl import PostgresHitlBackend
from app.models import AisScoreOut, FeedbackIn, ReasonCode, ScoreReason
from app.registry import PostgresRegistryBackend

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not os.getenv("HM_TEST_PG_DSN"), reason="set HM_TEST_PG_DSN to run"),
]

TS = datetime(2024, 6, 1, 3, 20, tzinfo=UTC)
TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"


def _out(trace_id: str) -> AisScoreOut:
    return AisScoreOut(
        mmsi=367000003,
        score=1.0,
        confidence=1.0,
        reasons=[ScoreReason(code=ReasonCode.OFF_CORRIDOR, severity=1.0, detail="10 km off")],
        hitl_required=True,
        trace_id=trace_id,
        latency_ms=0.5,
        n_history=120,
    )


def _swap_dsn(dsn: str, *, user: str, password: str, database: str) -> str:
    parts = urlsplit(dsn)
    host = parts.hostname or "127.0.0.1"
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit((parts.scheme, f"{user}:{password}@{host}{port}", f"/{database}", "", ""))


@contextlib.asynccontextmanager
async def fresh_tenant_db() -> AsyncIterator[str]:
    """A throwaway database OWNED by a throwaway NOSUPERUSER role, so FORCE
    RLS binds; yields the owner DSN, then drops both."""
    import asyncpg

    admin_dsn = os.environ["HM_TEST_PG_DSN"]
    suffix = uuid.uuid4().hex[:10]
    role, db, password = f"hm_rls_owner_{suffix}", f"hm_rls_{suffix}", "hm_rls_pw"

    admin = await asyncpg.connect(dsn=admin_dsn)
    try:
        await admin.execute(
            f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS"
        )
        await admin.execute(f"CREATE DATABASE {db} OWNER {role}")
    finally:
        await admin.close()
    try:
        yield _swap_dsn(admin_dsn, user=role, password=password, database=db)
    finally:
        admin = await asyncpg.connect(dsn=admin_dsn)
        try:
            await admin.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
            await admin.execute(f"DROP ROLE IF EXISTS {role}")
        finally:
            await admin.close()


async def _apply_full_schema(conn) -> None:
    from app import hitl as hitl_module
    from cdc.schema import ddl, tenancy

    for stmt in ddl.statements():
        await conn.execute(stmt)
    await conn.execute(hitl_module._DDL)
    for stmt in tenancy.statements():
        await conn.execute(stmt)


async def _set_tenant(conn, tenant_id: str) -> None:
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", tenant_id)


async def test_fail_closed_a_session_with_no_tenant_reads_zero_rows_and_cannot_write():
    import asyncpg

    async with fresh_tenant_db() as owner_dsn:
        seed = await asyncpg.connect(dsn=owner_dsn)
        try:
            await _apply_full_schema(seed)
            await _set_tenant(seed, TENANT_A)
            await seed.execute(
                "INSERT INTO watchlist (mmsi, reason) VALUES (368000001, 'rls drill')"
            )
            await seed.execute(
                """
                INSERT INTO hitl_queue (id, trace_id, mmsi, ts, score, reasons, confidence)
                VALUES ('rls-1', 'trace-rls-1', 368000001, now(), 1.0, '[]'::jsonb, 1.0)
                """
            )
            assert await seed.fetchval("SELECT count(*) FROM watchlist") == 1
        finally:
            await seed.close()

        # A brand-new session that never sets app.tenant_id: zero rows from
        # every tenant table (the policy compares against NULL), and any write
        # is rejected by the policy's WITH CHECK. Postgres enforces both; no
        # application code is involved.
        blank = await asyncpg.connect(dsn=owner_dsn)
        try:
            from cdc.schema import tenancy

            for table in tenancy.TENANT_TABLES:
                count = await blank.fetchval(f"SELECT count(*) FROM {table}")  # nosec B608
                assert count == 0, f"fail-open leak: {table} returned {count} rows"
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await blank.execute(
                    "INSERT INTO watchlist (mmsi, reason) VALUES (368000002, 'no tenant')"
                )
        finally:
            await blank.close()


async def test_cross_tenant_reads_are_blocked_by_postgres_not_the_application():
    import asyncpg

    async with fresh_tenant_db() as owner_dsn:
        seed = await asyncpg.connect(dsn=owner_dsn)
        try:
            await _apply_full_schema(seed)
            await _set_tenant(seed, TENANT_A)
            await seed.execute(
                "INSERT INTO watchlist (mmsi, reason) VALUES (368000010, 'tenant A row')"
            )
            await _set_tenant(seed, TENANT_B)
            await seed.execute(
                "INSERT INTO watchlist (mmsi, reason) VALUES (368000020, 'tenant B row')"
            )

            # tenant A: own row only, and a TARGETED read of B's row (the
            # drill M-tenant-leak shape: A's session querying for B's key)
            # comes back empty at the database layer.
            await _set_tenant(seed, TENANT_A)
            rows = await seed.fetch("SELECT mmsi FROM watchlist ORDER BY mmsi")
            assert [r["mmsi"] for r in rows] == [368000010]
            stolen = await seed.fetchrow("SELECT * FROM watchlist WHERE mmsi = 368000020")
            assert stolen is None

            # and tenant B is symmetric
            await _set_tenant(seed, TENANT_B)
            rows = await seed.fetch("SELECT mmsi FROM watchlist ORDER BY mmsi")
            assert [r["mmsi"] for r in rows] == [368000020]
        finally:
            await seed.close()


async def test_hitl_backend_sessions_are_tenant_scoped_end_to_end():
    async with fresh_tenant_db() as owner_dsn:
        backend_a = await PostgresHitlBackend.connect(owner_dsn, TENANT_A)
        backend_b = await PostgresHitlBackend.connect(owner_dsn, TENANT_B)
        try:
            await backend_a.enqueue("trace-a-1", _out("trace-a-1"), TS)
            await backend_b.enqueue("trace-b-1", _out("trace-b-1"), TS)

            pending_a = await backend_a.pending()
            pending_b = await backend_b.pending()
            assert [r["trace_id"] for r in pending_a] == ["trace-a-1"]
            assert [r["trace_id"] for r in pending_b] == ["trace-b-1"]

            # labeling ACROSS tenants fails exactly like a missing trace: the
            # UPDATE matches zero rows because RLS filtered B's row out of A's
            # session before the application ever saw it.
            with pytest.raises(HitlTraceNotFound):
                await backend_a.label(
                    FeedbackIn(trace_id="trace-b-1", label="correct", reviewer="arun")
                )
            assert (
                await backend_b.label(
                    FeedbackIn(trace_id="trace-b-1", label="correct", reviewer="arun")
                )
                == 0
            )
        finally:
            await backend_a.close()
            await backend_b.close()


async def test_registry_backend_sessions_are_tenant_scoped_end_to_end():
    async with fresh_tenant_db() as owner_dsn:
        backend_a = await PostgresRegistryBackend.connect(owner_dsn, TENANT_A)
        backend_b = await PostgresRegistryBackend.connect(owner_dsn, TENANT_B)
        try:
            await backend_a.upsert_watchlist(368000030, {"reason": "tenant A watch"})
            assert [r["mmsi"] for r in await backend_a.list_watchlist()] == [368000030]
            assert await backend_b.list_watchlist() == []
            assert await backend_b.delete_watchlist(368000030) is False
            # A's row survived B's blind delete: RLS filtered it from B's DELETE
            assert [r["mmsi"] for r in await backend_a.list_watchlist()] == [368000030]
        finally:
            await backend_a.close()
            await backend_b.close()
