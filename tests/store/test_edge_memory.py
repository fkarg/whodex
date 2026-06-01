"""InMemoryEdgeStore satisfies the EdgeStore contract."""

from __future__ import annotations

from tests.store.edge_store_contract import EdgeStoreContract
from whodex.store.memory import InMemoryEdgeStore


class TestInMemoryEdgeStore(EdgeStoreContract):
    def make_store(self) -> InMemoryEdgeStore:
        return InMemoryEdgeStore()
