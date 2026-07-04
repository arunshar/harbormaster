"""Schema-shape tests only; build_lake_writer itself needs a real pyiceberg
catalog and is deliberately excluded from the unit suite, mirroring
cdc/sinks/iceberg_audit.py's build_iceberg_writer (no AWS, no catalog, in
unit tests). Covered instead by the lake-backfill-smoke script and, later,
the Phase 3 e2e drills against a real local catalog.
"""

from __future__ import annotations

from lake.iceberg import (
    AIS_HISTORY_TABLE,
    CORRIDOR_EDGES_TABLE,
    CORRIDOR_NODES_TABLE,
    TABLE_SCHEMAS,
    ais_history_schema,
    corridor_edges_schema,
    corridor_nodes_schema,
)


def test_all_registered_tables_have_a_schema():
    assert set(TABLE_SCHEMAS) == {AIS_HISTORY_TABLE, CORRIDOR_NODES_TABLE, CORRIDOR_EDGES_TABLE}


def test_ais_history_schema_field_names():
    assert ais_history_schema().names == ["mmsi", "t", "lat", "lon", "sog", "cog"]


def test_corridor_nodes_schema_field_names():
    assert corridor_nodes_schema().names == ["node_id", "lat", "lon", "vessel_count"]


def test_corridor_edges_schema_field_names():
    assert corridor_edges_schema().names == ["from_node", "to_node", "frequency"]
