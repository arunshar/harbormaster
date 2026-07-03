"""Analyst-edited registry: vessels, watchlist, sanctions_flags (Phase 2, gate C1).

Postgres is the system of record; the serving API writes ONLY here. The online
store (DynamoDB + Redis) is CDC-fed by cdc/consumer and is read by the scorer's
WatchlistLookup; nothing in this module touches it. That separation is the whole
point of the phase: freshness of the online copy is Debezium's job, not the API's.

Two backends behind one interface, mirroring serving/app/hitl.py exactly:
  - MemoryRegistryBackend: hermetic, used by unit tests and when no DSN is set.
  - PostgresRegistryBackend: asyncpg; runs the idempotent cdc/schema DDL at
    connect (tables + REPLICA IDENTITY FULL + the harbormaster_cdc publication),
    upserts via INSERT ... ON CONFLICT DO UPDATE.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from app.config import Settings
from app.errors import RegistryEntryNotFound

log = structlog.get_logger(__name__)


def _sanctions_flag_id(mmsi: int, regime: str) -> str:
    # Kept in sync with cdc.schema.ddl.sanctions_flag_id by a unit test; the
    # serving wheel must not depend on the cdc package at runtime.
    return f"{int(mmsi)}:{regime.strip().lower()}"


class RegistryBackend(Protocol):
    async def upsert_vessel(self, mmsi: int, fields: dict[str, str]) -> dict[str, Any]: ...
    async def get_vessel(self, mmsi: int) -> dict[str, Any] | None: ...
    async def upsert_watchlist(self, mmsi: int, fields: dict[str, Any]) -> dict[str, Any]: ...
    async def delete_watchlist(self, mmsi: int) -> bool: ...
    async def list_watchlist(self) -> list[dict[str, Any]]: ...
    async def upsert_sanction(self, mmsi: int, fields: dict[str, str]) -> dict[str, Any]: ...
    async def delete_sanctions(self, mmsi: int) -> int: ...
    async def close(self) -> None: ...


class MemoryRegistryBackend:
    def __init__(self) -> None:
        self._vessels: dict[int, dict[str, Any]] = {}
        self._watchlist: dict[int, dict[str, Any]] = {}
        self._sanctions: dict[str, dict[str, Any]] = {}

    async def upsert_vessel(self, mmsi: int, fields: dict[str, str]) -> dict[str, Any]:
        row = {
            "mmsi": mmsi,
            "name": fields.get("name", ""),
            "flag_state": fields.get("flag_state", ""),
            "vessel_type": fields.get("vessel_type", ""),
            "updated_at": datetime.now(UTC),
        }
        self._vessels[mmsi] = row
        return dict(row)

    async def get_vessel(self, mmsi: int) -> dict[str, Any] | None:
        row = self._vessels.get(mmsi)
        return dict(row) if row else None

    async def upsert_watchlist(self, mmsi: int, fields: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC)
        prev = self._watchlist.get(mmsi)
        row = {
            "mmsi": mmsi,
            "reason": fields["reason"],
            "severity": float(fields.get("severity", 0.9)),
            "added_by": fields.get("added_by", ""),
            "created_at": prev["created_at"] if prev else now,
            "updated_at": now,
        }
        self._watchlist[mmsi] = row
        return dict(row)

    async def delete_watchlist(self, mmsi: int) -> bool:
        return self._watchlist.pop(mmsi, None) is not None

    async def list_watchlist(self) -> list[dict[str, Any]]:
        return [dict(r) for r in sorted(self._watchlist.values(), key=lambda r: r["mmsi"])]

    async def upsert_sanction(self, mmsi: int, fields: dict[str, str]) -> dict[str, Any]:
        now = datetime.now(UTC)
        fid = _sanctions_flag_id(mmsi, fields["regime"])
        prev = self._sanctions.get(fid)
        row = {
            "id": fid,
            "mmsi": mmsi,
            "regime": fields["regime"],
            "reference": fields.get("reference", ""),
            "created_at": prev["created_at"] if prev else now,
            "updated_at": now,
        }
        self._sanctions[fid] = row
        return dict(row)

    async def delete_sanctions(self, mmsi: int) -> int:
        gone = [k for k, v in self._sanctions.items() if v["mmsi"] == mmsi]
        for k in gone:
            del self._sanctions[k]
        return len(gone)

    async def close(self) -> None:
        return None


class PostgresRegistryBackend:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresRegistryBackend:
        import asyncpg  # lazy; only the real backend needs it

        from cdc.schema import ddl  # lazy; serving runs without cdc unless PG is used

        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2)
        async with pool.acquire() as conn:
            for stmt in ddl.statements():
                await conn.execute(stmt)
        return cls(pool)

    async def upsert_vessel(self, mmsi: int, fields: dict[str, str]) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO vessels (mmsi, name, flag_state, vessel_type, updated_at)
                VALUES ($1, $2, $3, $4, now())
                ON CONFLICT (mmsi) DO UPDATE SET
                    name = EXCLUDED.name,
                    flag_state = EXCLUDED.flag_state,
                    vessel_type = EXCLUDED.vessel_type,
                    updated_at = now()
                RETURNING *
                """,
                mmsi,
                fields.get("name", ""),
                fields.get("flag_state", ""),
                fields.get("vessel_type", ""),
            )
        return dict(row)

    async def get_vessel(self, mmsi: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM vessels WHERE mmsi = $1", mmsi)
        return dict(row) if row else None

    async def upsert_watchlist(self, mmsi: int, fields: dict[str, Any]) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO watchlist (mmsi, reason, severity, added_by, created_at, updated_at)
                VALUES ($1, $2, $3, $4, now(), now())
                ON CONFLICT (mmsi) DO UPDATE SET
                    reason = EXCLUDED.reason,
                    severity = EXCLUDED.severity,
                    added_by = EXCLUDED.added_by,
                    updated_at = now()
                RETURNING *
                """,
                mmsi,
                fields["reason"],
                float(fields.get("severity", 0.9)),
                fields.get("added_by", ""),
            )
        return dict(row)

    async def delete_watchlist(self, mmsi: int) -> bool:
        async with self._pool.acquire() as conn:
            status = await conn.execute("DELETE FROM watchlist WHERE mmsi = $1", mmsi)
        return not status.endswith(" 0")

    async def list_watchlist(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM watchlist ORDER BY mmsi")
        return [dict(r) for r in rows]

    async def upsert_sanction(self, mmsi: int, fields: dict[str, str]) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sanctions_flags (id, mmsi, regime, reference, created_at, updated_at)
                VALUES ($1, $2, $3, $4, now(), now())
                ON CONFLICT (id) DO UPDATE SET
                    reference = EXCLUDED.reference,
                    updated_at = now()
                RETURNING *
                """,
                _sanctions_flag_id(mmsi, fields["regime"]),
                mmsi,
                fields["regime"],
                fields.get("reference", ""),
            )
        return dict(row)

    async def delete_sanctions(self, mmsi: int) -> int:
        async with self._pool.acquire() as conn:
            status = await conn.execute("DELETE FROM sanctions_flags WHERE mmsi = $1", mmsi)
        try:
            return int(status.rsplit(" ", 1)[-1])
        except ValueError:  # pragma: no cover - asyncpg always returns "DELETE n"
            return 0

    async def close(self) -> None:
        await self._pool.close()


class RegistryStore:
    """Facade that picks a backend and exposes the registry to the API routes."""

    def __init__(self, backend: RegistryBackend) -> None:
        self.backend = backend

    @classmethod
    async def connect(cls, settings: Settings) -> RegistryStore:
        if settings.pg_dsn:
            try:
                backend: RegistryBackend = await PostgresRegistryBackend.connect(settings.pg_dsn)
                log.info("registry_backend", kind="postgres")
                return cls(backend)
            except Exception as exc:  # asyncpg missing or DB unreachable -> memory
                log.warning("registry_postgres_unavailable_fallback_memory", err=str(exc))
        return cls(MemoryRegistryBackend())

    async def upsert_vessel(self, mmsi: int, fields: dict[str, str]) -> dict[str, Any]:
        return await self.backend.upsert_vessel(mmsi, fields)

    async def get_vessel(self, mmsi: int) -> dict[str, Any]:
        row = await self.backend.get_vessel(mmsi)
        if row is None:
            raise RegistryEntryNotFound("vessel is not in the registry", mmsi=mmsi)
        return row

    async def upsert_watchlist(self, mmsi: int, fields: dict[str, Any]) -> dict[str, Any]:
        return await self.backend.upsert_watchlist(mmsi, fields)

    async def delete_watchlist(self, mmsi: int) -> None:
        if not await self.backend.delete_watchlist(mmsi):
            raise RegistryEntryNotFound("vessel is not on the watchlist", mmsi=mmsi)

    async def list_watchlist(self) -> list[dict[str, Any]]:
        return await self.backend.list_watchlist()

    async def upsert_sanction(self, mmsi: int, fields: dict[str, str]) -> dict[str, Any]:
        return await self.backend.upsert_sanction(mmsi, fields)

    async def delete_sanctions(self, mmsi: int) -> int:
        n = await self.backend.delete_sanctions(mmsi)
        if n == 0:
            raise RegistryEntryNotFound("vessel has no sanctions flags", mmsi=mmsi)
        return n

    async def close(self) -> None:
        await self.backend.close()
