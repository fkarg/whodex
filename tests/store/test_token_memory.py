"""InMemoryTokenStore satisfies the TokenStore contract."""

from __future__ import annotations

from tests.store.token_store_contract import TokenStoreContract
from whodex.store.memory import InMemoryTokenStore


class TestInMemoryTokenStore(TokenStoreContract):
    def make_store(self) -> InMemoryTokenStore:
        from whodex.domain.ids import SequentialIdFactory

        return InMemoryTokenStore(id_factory=SequentialIdFactory("TK"))
