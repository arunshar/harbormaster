"""The LSN-guarded idempotent applier (Phase 2, gate C4).

Exactly-once, delivered honestly: at-least-once transport + an idempotent sink
(docs/phases/PHASE_2.md, invariants 1-5). The applier consumes a batch of
parsed messages in delivery order and enforces the commit protocol:

    apply every event -> flush every sink -> THEN call commit()

If any sink raises, commit() is never reached, the Kafka offsets stay
uncommitted, and the redelivered batch converges through the per-(table, pk)
monotonic LSN guard (duplicates and stale events no-op). Tombstones are
compaction metadata and never touch state; heartbeats and schema changes were
already typed as Skip by the envelope parser.

Ops:
    c / u / r  -> StateSink.upsert(table, pk, after, lsn)   (snapshot reads
                  are plain upserts under the same guard; invariant 4)
    d          -> StateSink.soft_delete(table, pk, lsn)     (canonical marker;
                  no resurrection by lower-LSN stragglers; invariant 3)

Every data event lands in the audit sink with the guard's verdict, redeliveries
included: the audit table is transport truth, the state store is state truth,
and the difference between the two is the replay demo (invariant 5).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import structlog

from cdc.consumer.envelope import ChangeEvent, ParsedMessage, Skip, Tombstone
from cdc.sinks.base import AuditSink, EffectSink, StateSink

log = structlog.get_logger(__name__)


class ApplyError(RuntimeError):
    """A sink failed mid-batch; offsets must not be committed."""


@dataclass
class BatchResult:
    events: int = 0
    applied: int = 0
    guard_rejected: int = 0
    deletes_applied: int = 0
    tombstones: int = 0
    skips: dict[str, int] = field(default_factory=dict)

    def merge_skip(self, reason: str) -> None:
        self.skips[reason] = self.skips.get(reason, 0) + 1


class Applier:
    def __init__(
        self,
        *,
        store: StateSink,
        effects: Sequence[EffectSink] = (),
        audit: AuditSink | None = None,
    ) -> None:
        self._store = store
        self._effects = tuple(effects)
        self._audit = audit

    def apply_batch(
        self, messages: Iterable[ParsedMessage], commit: Callable[[], None]
    ) -> BatchResult:
        """Apply one delivery batch, then flush, then commit. Raises ApplyError
        (offsets uncommitted) if any sink fails; redelivery converges."""
        result = BatchResult()
        try:
            for msg in messages:
                self._apply_one(msg, result)
            self._store.flush()
            for effect in self._effects:
                effect.flush()
            if self._audit is not None:
                self._audit.flush()
        except Exception as exc:
            raise ApplyError(f"sink failure mid-batch; offsets not committed: {exc}") from exc
        commit()
        return result

    def _apply_one(self, msg: ParsedMessage, result: BatchResult) -> None:
        if isinstance(msg, Skip):
            result.merge_skip(msg.reason)
            return
        if isinstance(msg, Tombstone):
            result.tombstones += 1
            return
        event: ChangeEvent = msg
        result.events += 1

        if event.is_delete:
            applied = self._store.soft_delete(event.table, event.pk, event.lsn)
            if applied:
                result.deletes_applied += 1
        else:
            applied = self._store.upsert(event.table, event.pk, event.after or {}, event.lsn)

        if applied:
            result.applied += 1
            for effect in self._effects:
                effect.on_applied(event)
        else:
            result.guard_rejected += 1
            log.debug(
                "cdc_guard_rejected", table=event.table, pk=event.pk, op=event.op, lsn=event.lsn
            )

        if self._audit is not None:
            self._audit.append(event, applied)
