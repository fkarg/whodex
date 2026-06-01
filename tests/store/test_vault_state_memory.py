"""InMemoryVaultStateStore satisfies the VaultStateStore contract."""

from __future__ import annotations

from tests.store.vault_state_contract import VaultStateStoreContract
from whodex.store.memory import InMemoryVaultStateStore


class TestInMemoryVaultStateStore(VaultStateStoreContract):
    def make_store(self) -> InMemoryVaultStateStore:
        return InMemoryVaultStateStore()
