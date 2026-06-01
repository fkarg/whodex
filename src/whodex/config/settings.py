from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from whodex.domain.clock import Clock, SystemClock
from whodex.domain.events import RawRecord
from whodex.domain.ids import IdFactory, UlidIdFactory
from whodex.domain.trust import DEFAULT_TRUST
from whodex.sources.base import PullSource
from whodex.sources.fake import FakeSource
from whodex.store.interfaces import (
    DerivedStore,
    EdgeStore,
    EntityStore,
    LedgerStore,
    ProjectionStore,
)
from whodex.store.memory import (
    InMemoryDerivedStore,
    InMemoryEdgeStore,
    InMemoryEntityStore,
    InMemoryLedgerStore,
    InMemoryProjectionStore,
)
from whodex.sync.hub import IngestionHub, StoreIdentityResolver


@dataclass
class App:
    ledger: LedgerStore  # InMemory or SQLite, structurally
    projection: ProjectionStore  # InMemory or SQLite, structurally
    entities: EntityStore  # identity resolution
    edges: EdgeStore  # graph edges
    derived: DerivedStore  # changes, conflicts, repairs, reminders
    hub: IngestionHub
    sources: list[PullSource]
    trust: dict[str, int]
    clock: Clock


def build_app(
    *,
    demo: bool = False,
    vault: Path | None = None,
    db: Path | None = None,
    ids: IdFactory | None = None,
    clock: Clock | None = None,
) -> App:
    clock = clock or SystemClock()
    sources: list[PullSource] = []
    entity_ids = ids or UlidIdFactory()
    ledger: LedgerStore
    projection: ProjectionStore
    entities: EntityStore

    edge_store: EdgeStore
    derived_store: DerivedStore

    if db is not None:
        # Durable SQLite path
        from whodex.store.sqlite import (
            SqliteDerivedStore,
            SqliteEdgeStore,
            SqliteEntityStore,
            SqliteLedgerStore,
            SqliteProjectionStore,
        )

        url = f"sqlite:///{db}"
        jsonl_dir = (vault / ".whodex" / "events") if vault is not None else None
        ledger = SqliteLedgerStore(url, jsonl_dir=jsonl_dir)
        projection = SqliteProjectionStore(url)
        entities = SqliteEntityStore(url, id_factory=entity_ids)
        edge_store = SqliteEdgeStore(url)
        derived_store = SqliteDerivedStore(url)
    else:
        # In-memory path — same durable resolver over an in-memory entity store (parity)
        ledger = InMemoryLedgerStore()
        projection = InMemoryProjectionStore()
        entities = InMemoryEntityStore(entity_ids)
        edge_store = InMemoryEdgeStore()
        derived_store = InMemoryDerivedStore()

    identity = StoreIdentityResolver(entities, ledger, ids=UlidIdFactory(), clock=clock)
    hub = IngestionHub(ids=UlidIdFactory(), clock=clock, identity=identity)

    if vault is not None:
        from whodex.sources.obsidian import ObsidianSource

        sources.append(ObsidianSource(vault))

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
        ledger=ledger,
        projection=projection,
        entities=entities,
        edges=edge_store,
        derived=derived_store,
        hub=hub,
        sources=sources,
        trust=dict(DEFAULT_TRUST),
        clock=clock,
    )
