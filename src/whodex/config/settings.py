from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from whodex.domain.clock import Clock, SystemClock
from whodex.domain.events import RawRecord
from whodex.domain.ids import IdFactory, UlidIdFactory
from whodex.domain.trust import DEFAULT_TRUST
from whodex.sources.base import PullSource
from whodex.sources.fake import FakeSource
from whodex.store.interfaces import LedgerStore, ProjectionStore
from whodex.store.memory import InMemoryEntityStore, InMemoryLedgerStore, InMemoryProjectionStore
from whodex.sync.hub import IngestionHub, IdentityResolver, StoreIdentityResolver


@dataclass
class App:
    ledger: LedgerStore  # InMemory or SQLite, structurally
    projection: ProjectionStore  # InMemory or SQLite, structurally
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

    if db is not None:
        # Durable SQLite path
        from whodex.store.sqlite import SqliteEntityStore, SqliteLedgerStore, SqliteProjectionStore

        engine_ids = ids or UlidIdFactory()
        url = f"sqlite:///{db}"
        jsonl_dir = (vault / ".whodex" / "events") if vault is not None else None
        ledger: LedgerStore = SqliteLedgerStore(url, jsonl_dir=jsonl_dir)
        projection: ProjectionStore = SqliteProjectionStore(url)
        entities = SqliteEntityStore(url, id_factory=engine_ids)
        identity: Any = StoreIdentityResolver(
            entities,
            ledger,
            ids=UlidIdFactory(),
            clock=clock,
        )
        hub = IngestionHub(ids=UlidIdFactory(), clock=clock, identity=identity)
    else:
        # In-memory path
        entity_ids = ids or UlidIdFactory()
        ledger = InMemoryLedgerStore()
        projection = InMemoryProjectionStore()
        entities_mem = InMemoryEntityStore(UlidIdFactory())
        identity = IdentityResolver(UlidIdFactory())
        hub = IngestionHub(ids=entity_ids, clock=clock, identity=identity)

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
        hub=hub,
        sources=sources,
        trust=dict(DEFAULT_TRUST),
        clock=clock,
    )
