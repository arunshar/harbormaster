"""Redis invalidation sink (Phase 2, gate C5).

Write-invalidate, not write-through: on any APPLIED change the consumer DELs
the vessel's cache key and the scorer's next read-through (serving/app/
watchlist.py) repopulates from DynamoDB. The DEL fires after the store write
returned (the applier calls effects only for applied events), so a reader can
never repopulate the cache from pre-change state. The TTL on the serving side
is only the backstop for a lost invalidation.

The key rule is duplicated from serving/app/watchlist.py redis_key(); a test
in cdc/tests/test_sinks.py holds the two identical.
"""

from __future__ import annotations

from typing import Any

import structlog

from cdc.consumer.envelope import ChangeEvent
from cdc.sinks.dynamo import SANCTIONS_TABLE, _split_sanctions_id

log = structlog.get_logger(__name__)

REDIS_KEY_PREFIX = "hm:online:"


def redis_key_for_event(event: ChangeEvent) -> str:
    """The cache key an applied change invalidates. Everything keys by mmsi."""
    if event.table == SANCTIONS_TABLE:
        flag_id = event.pk.get("id")
        if flag_id is None:
            raise ValueError(f"sanctions event pk has no id: {event.pk!r}")
        mmsi, _ = _split_sanctions_id(flag_id)
        return f"{REDIS_KEY_PREFIX}{int(mmsi)}"
    mmsi = event.pk.get("mmsi")
    if mmsi is None:
        raise ValueError(f"{event.table} event pk has no mmsi: {event.pk!r}")
    return f"{REDIS_KEY_PREFIX}{int(mmsi)}"


class RedisInvalidationSink:
    """EffectSink: DEL the vessel's online-status key on every applied change."""

    def __init__(self, *, client: Any) -> None:
        self._client = client  # needs only .delete(key)

    def on_applied(self, event: ChangeEvent) -> None:
        key = redis_key_for_event(event)
        self._client.delete(key)
        log.debug("cdc_cache_invalidated", key=key, table=event.table, lsn=event.lsn)

    def flush(self) -> None:
        return None
