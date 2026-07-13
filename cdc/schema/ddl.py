"""Registry schema + logical-replication DDL (Phase 2, gate C1).

Postgres is the system of record for the analyst-edited registry tables
(vessels, watchlist, sanctions_flags). Every statement here is idempotent so
the DDL can run at every backend connect, mirroring serving/app/hitl.py:
CREATE TABLE IF NOT EXISTS, re-runnable ALTER ... REPLICA IDENTITY, and a
guarded DO block for the publication (Postgres has no CREATE PUBLICATION IF
NOT EXISTS).

REPLICA IDENTITY FULL puts the complete before-image of updates and deletes on
the WAL, which keeps the Iceberg cdc_audit trail complete. The tables are tiny,
so the extra WAL volume is negligible (docs/phases/PHASE_2.md, decisions).

The publication is created HERE, explicitly; the Debezium connector runs with
publication.autocreate.mode=disabled (cdc/connector/config.py), so ownership of
the replication surface stays with the schema, not the capture tool.
"""

from __future__ import annotations

import hashlib

# Single source of truth for the replication surface. The connector config
# generator (cdc/connector/config.py) and the consumer both import these.
CDC_TABLES: tuple[str, ...] = ("vessels", "watchlist", "sanctions_flags")
PUBLICATION_NAME = "harbormaster_cdc"
SLOT_NAME = "harbormaster_cdc"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"

_VESSELS = """
CREATE TABLE IF NOT EXISTS vessels (
    tenant_id   UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000'::uuid,
    mmsi        BIGINT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    flag_state  TEXT NOT NULL DEFAULT '',
    vessel_type TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, mmsi)
);
""".strip()

_WATCHLIST = """
CREATE TABLE IF NOT EXISTS watchlist (
    tenant_id   UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000'::uuid,
    mmsi        BIGINT NOT NULL,
    reason      TEXT NOT NULL,
    severity    DOUBLE PRECISION NOT NULL DEFAULT 0.9,
    added_by    TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, mmsi)
);
""".strip()

# id is the deterministic "<mmsi>:<regime>" built by sanctions_flag_id(), so an
# analyst re-adding the same regime upserts instead of duplicating, and the CDC
# message key stays a single stable column. The CHECK enforces the id shape at
# the system of record, so no writer (this API or any out-of-band one) can mint
# a "<mmsi>:" poison id the CDC key mapper would reject.
_SANCTIONS = """
CREATE TABLE IF NOT EXISTS sanctions_flags (
    tenant_id   UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000'::uuid,
    id          TEXT NOT NULL CHECK (id ~ '^[0-9]+:.'),
    mmsi        BIGINT NOT NULL,
    regime      TEXT NOT NULL CHECK (btrim(regime) <> ''),
    reference   TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
""".strip()

_SANCTIONS_IDX = (
    "CREATE INDEX IF NOT EXISTS sanctions_flags_tenant_mmsi_idx "
    "ON sanctions_flags (tenant_id, mmsi);"
)

_REPLICA_IDENTITY = tuple(f"ALTER TABLE {t} REPLICA IDENTITY FULL;" for t in CDC_TABLES)

_PUBLICATION = f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication WHERE pubname = '{PUBLICATION_NAME}'
    ) THEN
        CREATE PUBLICATION {PUBLICATION_NAME} FOR TABLE {", ".join(CDC_TABLES)};
    END IF;
END
$$;
""".strip()  # nosec B608  # PUBLICATION_NAME and CDC_TABLES are module-level constants, not untrusted input


def table_statements() -> tuple[str, ...]:
    """Create the registry tables without assuming a tenancy migration ran."""
    return (_VESSELS, _WATCHLIST, _SANCTIONS)


def post_tenancy_statements() -> tuple[str, ...]:
    """DDL that is safe only after every registry table has ``tenant_id``."""
    return (_SANCTIONS_IDX, *_REPLICA_IDENTITY, _PUBLICATION)


def statements() -> tuple[str, ...]:
    """The ordered, individually idempotent DDL statements for a fresh schema."""
    return (*table_statements(), *post_tenancy_statements())


def canonical_ddl() -> str:
    """The canonical DDL string the gate-C1 checksum is taken over."""
    return "\n\n".join(statements()) + "\n"


def ddl_sha256() -> str:
    return hashlib.sha256(canonical_ddl().encode()).hexdigest()


def sanctions_flag_id(mmsi: int, regime: str) -> str:
    """Deterministic sanctions_flags primary key: one row per (vessel, regime).
    A blank regime is refused: it would mint the "<mmsi>:" poison id the CDC
    key mapper rejects (mirrored in serving/app/registry.py and the CHECK)."""
    normalized = regime.strip().lower()
    if not normalized:
        raise ValueError("regime must not be blank")
    return f"{int(mmsi)}:{normalized}"
