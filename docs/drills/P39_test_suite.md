# P39 full local verification (2026-07-13)

## Source gates

```text
.venv/bin/ruff check serving streaming cdc lake mlops tests scripts infra/lambda
.venv/bin/ruff format --check serving streaming cdc lake mlops tests scripts infra/lambda
.venv/bin/bandit -q -c pyproject.toml -r serving streaming cdc lake mlops
PYTHONPATH=streaming .venv/bin/python -c \
  "from replay.loader import verify_fixture; assert verify_fixture()"
.venv/bin/pytest -q --cov --cov-report=term-missing \
  --cov-report=xml:/tmp/harbormaster-p39-final-source-coverage.xml \
  --junitxml=/tmp/harbormaster-p39-final-source-junit.xml
940 passed, 20 skipped, 16 warnings in 11.92s
Total coverage: 82.49%
```

Ruff, Bandit, and the replay checksum check exited with status 0. The pytest
artifacts are `/tmp/harbormaster-p39-final-source-junit.xml` and
`/tmp/harbormaster-p39-final-source-coverage.xml`. The warnings are dependency
deprecations from Starlette, Great Expectations, PyParsing, and Marshmallow.

## PostgreSQL and tenant smoke

The tenant/RLS integration module, including the explicit legacy-schema
migration, same-MMSI backend upserts, policy-drift checks, and the shared schema
bootstrap lock, ran against a throwaway PostgreSQL 16 container with logical
replication enabled:

```text
HM_TEST_PG_DSN=postgresql://... .venv/bin/python -m pytest -q \
  serving/tests/test_tenant_rls.py \
  --junitxml=/tmp/harbormaster-p39-coverage-postgres-junit.xml
10 passed in 2.42s
```

The focused line-and-branch measurement for the new migration module was 98.73%.
Its coverage artifact is
`/tmp/harbormaster-p39-migration-final-coverage.xml`.

`make phase5-tenant-smoke` also passed against the same disposable Postgres 16
convention. It verified same-MMSI composite keys across vessels, watchlist, and
sanctions, tenant-isolated reads, fail-closed reads and writes without a tenant
GUC, and the pinned per-tenant burn-rate boundary. Its transcript is
`/tmp/harbormaster-p39-final-tenant-smoke.log`; the command trap removed the
container.

## Local production-image verification

The production serving image was built locally as `harbormaster-p39:dev` and run
in two containers, each with two Uvicorn workers, against one fresh database
owned by a `NOSUPERUSER NOBYPASSRLS` role. The same MMSI, `368000303`, was written
under two tenants in `vessels`, `watchlist`, and `sanctions_flags`. Each API read
only its tenant's values, and the database held two rows with two distinct tenant
IDs in every table. The primary keys were exactly `(tenant_id, mmsi)` for vessels
and watchlist and `(tenant_id, id)` for sanctions. The container logs contained no
traceback, in-memory fallback, uniqueness violation, or duplicate-DDL error.

Artifacts: `/tmp/harbormaster-p39-final-image-build.log`,
`/tmp/harbormaster-p39-final-app-a.log`,
`/tmp/harbormaster-p39-final-app-b.log`,
`/tmp/harbormaster-p39-final-db-counts.txt`, and
`/tmp/harbormaster-p39-final-db-primary-keys.txt`.

This evidence is local. No live AWS database migration or derived-store rebuild
was run.
