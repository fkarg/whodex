from datetime import UTC, datetime

import pytest

from tests.conftest import raw
from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.domain.trust import DEFAULT_TRUST
from whodex.sources.fake import FakeSource
from whodex.store.memory import InMemoryLedgerStore, InMemoryProjectionStore
from whodex.store.sqlite import SqliteLedgerStore
from whodex.sync.engine import run_sync
from whodex.sync.hub import IdentityResolver, IngestionHub


def _hub():
    return IngestionHub(
        ids=SequentialIdFactory("OBS"),
        clock=FixedClock(datetime(2026, 2, 1, tzinfo=UTC)),
        identity=IdentityResolver(SequentialIdFactory("E")),
    )


@pytest.mark.e2e
def test_job_change_produces_exactly_one_change_and_none_on_rerun():
    ledger, proj, hub = InMemoryLedgerStore(), InMemoryProjectionStore(), _hub()
    first_src = FakeSource(
        records=[
            raw(
                identity={"email": "a@b.com"},
                payload={"display_name": "Jane", "title": "Engineer"},
                observed=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ]
    )
    r1 = run_sync(
        [first_src],
        ledger=ledger,
        projection=proj,
        hub=hub,
        trust=DEFAULT_TRUST,
        now=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert r1.changes == 0  # initial fill

    change_src = FakeSource(
        records=[
            raw(
                identity={"email": "a@b.com"},
                payload={"display_name": "Jane", "title": "Staff Engineer"},
                observed=datetime(2026, 1, 15, tzinfo=UTC),
            )
        ]
    )
    r2 = run_sync(
        [change_src],
        ledger=ledger,
        projection=proj,
        hub=hub,
        trust=DEFAULT_TRUST,
        now=datetime(2026, 2, 2, tzinfo=UTC),
    )
    assert r2.changes == 1
    assert proj.load()["E-00000001"].fields["job.title"].value == "Staff Engineer"

    r3 = run_sync(
        [change_src],
        ledger=ledger,
        projection=proj,
        hub=hub,
        trust=DEFAULT_TRUST,
        now=datetime(2026, 2, 3, tzinfo=UTC),
    )
    assert r3.changes == 0  # no spurious change/suggestion on re-run


@pytest.mark.e2e
def test_sqlite_and_memory_materialize_identically():
    records = [raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})]

    def project_with(ledger):
        proj = InMemoryProjectionStore()
        run_sync(
            [FakeSource(records=records)],
            ledger=ledger,
            projection=proj,
            hub=_hub(),
            trust=DEFAULT_TRUST,
            now=datetime(2026, 2, 1, tzinfo=UTC),
        )
        return proj.load()

    mem = project_with(InMemoryLedgerStore())
    sql = project_with(SqliteLedgerStore("sqlite://"))
    assert mem.keys() == sql.keys()
    assert (
        mem["E-00000001"].fields["job.title"].value == sql["E-00000001"].fields["job.title"].value
    )
