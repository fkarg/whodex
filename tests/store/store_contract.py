"""Behavioural contract every LedgerStore must satisfy. Subclass and set `make_store`."""

from tests.conftest import obs


class LedgerStoreContract:
    def make_store(self):  # override
        raise NotImplementedError

    def test_append_then_read_observations(self):
        store = self.make_store()
        o = obs(entity="E1", field="job.title", value="Eng")
        store.append_observations([o])
        read = store.read_events().observations
        assert len(read) == 1
        assert read[0].id == o.id

    def test_append_is_additive_across_calls(self):
        store = self.make_store()
        store.append_observations([obs(entity="E1", field="email", value="a@b.com")])
        store.append_observations([obs(entity="E1", field="job.title", value="Eng")])
        assert len(store.read_events().observations) == 2

    def test_read_empty_store(self):
        store = self.make_store()
        ev = store.read_events()
        assert ev.observations == [] and ev.interactions == [] and ev.user_actions == []
