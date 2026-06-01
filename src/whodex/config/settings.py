from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from whodex.domain.clock import Clock, SystemClock
from whodex.domain.events import RawRecord
from whodex.domain.ids import IdFactory, UlidIdFactory
from whodex.domain.trust import DEFAULT_TRUST
from whodex.notifiers.impls import TUINotifier
from whodex.notifiers.interface import Notifier
from whodex.sources.base import PullSource
from whodex.sources.fake import FakeSource
from whodex.store.interfaces import (
    DerivedStore,
    EdgeStore,
    EntityStore,
    LedgerStore,
    NotificationStore,
    ProjectionStore,
    SyncTokenStore,
    TokenStore,
    VaultStateStore,
)
from whodex.store.memory import (
    InMemoryDerivedStore,
    InMemoryEdgeStore,
    InMemoryEntityStore,
    InMemoryLedgerStore,
    InMemoryNotificationStore,
    InMemoryProjectionStore,
    InMemorySyncTokenStore,
    InMemoryTokenStore,
    InMemoryVaultStateStore,
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
    vault_state_store: VaultStateStore  # per-file vault tracking (echo suppression)
    tokens: TokenStore  # revocable bearer tokens
    sync_tokens: SyncTokenStore  # sync-token persistence for pull sources (e.g. Google)
    notifications: NotificationStore  # append-only notification store (dedupe by dedupe_key)
    notifiers: list[Notifier]  # registered notifier sinks (default: [TUINotifier()])


def build_app(
    *,
    demo: bool = False,
    vault: Path | None = None,
    db: Path | None = None,
    ids: IdFactory | None = None,
    clock: Clock | None = None,
    google_env: Mapping[str, str] | None = None,
) -> App:
    clock = clock or SystemClock()
    sources: list[PullSource] = []
    entity_ids = ids or UlidIdFactory()
    ledger: LedgerStore
    projection: ProjectionStore
    entities: EntityStore

    edge_store: EdgeStore
    derived_store: DerivedStore
    vault_state_store: VaultStateStore
    token_store: TokenStore
    sync_token_store: SyncTokenStore

    notification_store: NotificationStore
    if db is not None:
        # Durable SQLite path
        from whodex.store.sqlite import (
            SqliteDerivedStore,
            SqliteEdgeStore,
            SqliteEntityStore,
            SqliteLedgerStore,
            SqliteNotificationStore,
            SqliteProjectionStore,
            SqliteSyncTokenStore,
            SqliteTokenStore,
            SqliteVaultStateStore,
        )

        url = f"sqlite:///{db}"
        jsonl_dir = (vault / ".whodex" / "events") if vault is not None else None
        ledger = SqliteLedgerStore(url, jsonl_dir=jsonl_dir)
        projection = SqliteProjectionStore(url)
        entities = SqliteEntityStore(url, id_factory=entity_ids)
        edge_store = SqliteEdgeStore(url)
        derived_store = SqliteDerivedStore(url)
        vault_state_store = SqliteVaultStateStore(url)
        token_store = SqliteTokenStore(url, id_factory=UlidIdFactory())
        sync_token_store = SqliteSyncTokenStore(url)
        notification_store = SqliteNotificationStore(url)
    else:
        # In-memory path — same durable resolver over an in-memory entity store (parity)
        ledger = InMemoryLedgerStore()
        projection = InMemoryProjectionStore()
        entities = InMemoryEntityStore(entity_ids)
        edge_store = InMemoryEdgeStore()
        derived_store = InMemoryDerivedStore()
        vault_state_store = InMemoryVaultStateStore()
        token_store = InMemoryTokenStore(id_factory=UlidIdFactory())
        sync_token_store = InMemorySyncTokenStore()
        notification_store = InMemoryNotificationStore()

    identity = StoreIdentityResolver(entities, ledger, ids=UlidIdFactory(), clock=clock)
    hub = IngestionHub(ids=UlidIdFactory(), clock=clock, identity=identity)

    if vault is not None:
        from whodex.sources.obsidian import ObsidianSource

        sources.append(ObsidianSource(vault, state_store=vault_state_store))

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

    # Optional Google Contacts wiring: only when credentials are present in google_env.
    # When google_env is None or missing required vars, Google is silently skipped.
    if google_env is not None:
        import httpx

        from whodex.sources.google.auth import GoogleCredentialsConfig, GoogleTokenProvider
        from whodex.sources.google.contacts import GoogleContacts

        google_config = GoogleCredentialsConfig.from_env(google_env)
        if google_config is not None:
            token_provider = GoogleTokenProvider(google_config)
            sources.append(
                GoogleContacts(
                    http=httpx.Client(),
                    token=token_provider.access_token,
                    clock=clock,
                    sync_token_store=sync_token_store,
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
        vault_state_store=vault_state_store,
        tokens=token_store,
        sync_tokens=sync_token_store,
        notifications=notification_store,
        notifiers=[TUINotifier()],
    )
