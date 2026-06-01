"""SqliteEntityStore satisfies the EntityStore contract."""

from __future__ import annotations

from tests.store.entity_store_contract import EntityStoreContract
from whodex.domain.ids import SequentialIdFactory
from whodex.store.sqlite import SqliteEntityStore


class TestSqliteEntityStore(EntityStoreContract):
    def make_store(self) -> SqliteEntityStore:
        return SqliteEntityStore(url="sqlite://", id_factory=SequentialIdFactory())
