"""InMemorySyncTokenStore satisfies the SyncTokenStore contract."""

from __future__ import annotations

from tests.store.sync_token_store_contract import SyncTokenStoreContract
from whodex.store.memory import InMemorySyncTokenStore


class TestInMemorySyncTokenStore(SyncTokenStoreContract):
    def make_store(self) -> InMemorySyncTokenStore:
        return InMemorySyncTokenStore()
