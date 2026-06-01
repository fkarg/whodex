from tests.store.store_contract import LedgerStoreContract
from whodex.store.sqlite import SqliteLedgerStore


class TestSqliteLedger(LedgerStoreContract):
    def make_store(self):
        return SqliteLedgerStore("sqlite://")  # in-memory engine


def test_observation_survives_roundtrip_through_sqlite():
    from tests.conftest import obs

    store = SqliteLedgerStore("sqlite://")
    o = obs(entity="E1", field="job.title", value="Eng")
    store.append_observations([o])
    back = store.read_events().observations[0]
    assert back == o
