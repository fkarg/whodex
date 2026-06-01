"""InMemoryProjectionStore satisfies the ProjectionStore contract."""

from __future__ import annotations

from tests.store.projection_store_contract import ProjectionStoreContract
from whodex.store.memory import InMemoryProjectionStore


class TestInMemoryProjectionStore(ProjectionStoreContract):
    def make_store(self) -> InMemoryProjectionStore:
        return InMemoryProjectionStore()
