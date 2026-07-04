"""Iceberg writer for the Phase 3 lake tables (ais_history, corridor_graph_nodes,
corridor_graph_edges). Extends the cdc/sinks/iceberg_audit.py catalog pattern
(same catalog_props shape: local SQLite catalog + file warehouse, or Glue
catalog + the S3 lake bucket on AWS) generalized to more than one fixed
table/schema, rather than duplicating a bespoke writer per table.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

AIS_HISTORY_TABLE = "ais_history"
CORRIDOR_NODES_TABLE = "corridor_graph_nodes"
CORRIDOR_EDGES_TABLE = "corridor_graph_edges"


def ais_history_schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("mmsi", pa.int64(), nullable=False),
            pa.field("t", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("lat", pa.float64(), nullable=False),
            pa.field("lon", pa.float64(), nullable=False),
            pa.field("sog", pa.float64()),
            pa.field("cog", pa.float64()),
        ]
    )


def corridor_nodes_schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("node_id", pa.string(), nullable=False),
            pa.field("lat", pa.float64(), nullable=False),
            pa.field("lon", pa.float64(), nullable=False),
            pa.field("vessel_count", pa.int64(), nullable=False),
        ]
    )


def corridor_edges_schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("from_node", pa.string(), nullable=False),
            pa.field("to_node", pa.string(), nullable=False),
            pa.field("frequency", pa.int64(), nullable=False),
        ]
    )


TABLE_SCHEMAS: dict[str, Callable[[], Any]] = {
    AIS_HISTORY_TABLE: ais_history_schema,
    CORRIDOR_NODES_TABLE: corridor_nodes_schema,
    CORRIDOR_EDGES_TABLE: corridor_edges_schema,
}


def build_lake_writer(
    *, catalog_props: dict[str, str], namespace: str = "hm", table_name: str
) -> Callable[[list[dict[str, Any]]], None]:
    """The real pyiceberg appender for a lake table. catalog_props examples:

    local (backfill smoke / drills):
        {"type": "sql",
         "uri": "sqlite:///.lake-warehouse/catalog.db",
         "warehouse": "file://.lake-warehouse"}
    AWS showcase (Athena-queryable, Feast's offline store reads through here):
        {"type": "glue", "warehouse": "s3://<lake-bucket>/iceberg"}
    """
    import pyarrow as pa
    from pyiceberg.catalog import load_catalog

    if table_name not in TABLE_SCHEMAS:
        raise ValueError(f"no schema registered for lake table: {table_name}")
    schema = TABLE_SCHEMAS[table_name]()

    catalog = load_catalog(f"hm_lake_{table_name}", **catalog_props)
    try:
        catalog.create_namespace_if_not_exists(namespace)
    except AttributeError:  # older pyiceberg
        try:
            catalog.create_namespace(namespace)
        except Exception:  # already exists
            pass
    identifier = f"{namespace}.{table_name}"
    try:
        table = catalog.load_table(identifier)
    except Exception:
        table = catalog.create_table(identifier, schema=schema)

    def writer(rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        table.append(pa.Table.from_pylist(rows, schema=schema))

    return writer
