from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from whodex.domain.clock import Clock, SystemClock
from whodex.domain.events import RawRecord
from whodex.domain.ids import IdFactory, UlidIdFactory
from whodex.domain.trust import DEFAULT_TRUST
from whodex.sources.base import PullSource
from whodex.sources.fake import FakeSource
from whodex.store.memory import InMemoryLedgerStore, InMemoryProjectionStore
from whodex.sync.hub import IdentityResolver, IngestionHub


@dataclass
class App:
    ledger: InMemoryLedgerStore
    projection: InMemoryProjectionStore
    hub: IngestionHub
    sources: list[PullSource]
    trust: dict[str, int]
    clock: Clock


def build_app(
    *, demo: bool = False, ids: IdFactory | None = None, clock: Clock | None = None
) -> App:
    ids = ids or UlidIdFactory()
    clock = clock or SystemClock()
    sources: list[PullSource] = []
    if demo:
        sources.append(
            FakeSource(
                records=[
                    RawRecord(
                        source="fake",
                        identity={"email": "jane@demo.com"},
                        payload={"display_name": "Jane Demo", "title": "Founder"},
                        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                ]
            )
        )
    return App(
        ledger=InMemoryLedgerStore(),
        projection=InMemoryProjectionStore(),
        hub=IngestionHub(ids=ids, clock=clock, identity=IdentityResolver(UlidIdFactory())),
        sources=sources,
        trust=dict(DEFAULT_TRUST),
        clock=clock,
    )
