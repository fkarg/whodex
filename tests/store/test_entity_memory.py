"""InMemoryEntityStore satisfies the EntityStore contract."""

from __future__ import annotations

from tests.store.entity_store_contract import EntityStoreContract
from whodex.domain.ids import SequentialIdFactory
from whodex.store.memory import InMemoryEntityStore


class TestInMemoryEntityStore(EntityStoreContract):
    def make_store(self) -> InMemoryEntityStore:
        return InMemoryEntityStore(id_factory=SequentialIdFactory())
