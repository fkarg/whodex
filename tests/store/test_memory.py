from tests.store.store_contract import LedgerStoreContract
from whodex.store.memory import InMemoryLedgerStore


class TestInMemoryLedger(LedgerStoreContract):
    def make_store(self):
        return InMemoryLedgerStore()
