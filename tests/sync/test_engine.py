from datetime import UTC, datetime

from tests.conftest import raw
from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.domain.trust import DEFAULT_TRUST
from whodex.sources.fake import FakeSource
from whodex.store.memory import InMemoryLedgerStore, InMemoryProjectionStore
from whodex.sync.engine import run_sync
from whodex.sync.hub import IdentityResolver, IngestionHub


def _wiring():
    ledger = InMemoryLedgerStore()
    proj = InMemoryProjectionStore()
    hub = IngestionHub(
        ids=SequentialIdFactory("OBS"),
        clock=FixedClock(datetime(2026, 2, 1, tzinfo=UTC)),
        identity=IdentityResolver(SequentialIdFactory("E")),
    )
    return ledger, proj, hub


def test_run_sync_materializes_state():
    ledger, proj, hub = _wiring()
    src = FakeSource(
        records=[
            raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
        ]
    )
    report = run_sync(
        [src],
        ledger=ledger,
        projection=proj,
        hub=hub,
        trust=DEFAULT_TRUST,
        now=datetime(2026, 2, 1, tzinfo=UTC),
    )
    state = proj.load()
    assert state["E-00000001"].fields["job.title"].value == "Eng"
    assert report.observations_ingested == 2
    assert report.changes == 0  # initial fill


def test_rerun_is_idempotent_no_changes():
    ledger, proj, hub = _wiring()
    src = FakeSource(records=[raw(identity={"email": "a@b.com"}, payload={"title": "Eng"})])
    run_sync(
        [src],
        ledger=ledger,
        projection=proj,
        hub=hub,
        trust=DEFAULT_TRUST,
        now=datetime(2026, 2, 1, tzinfo=UTC),
    )
    report2 = run_sync(
        [src],
        ledger=ledger,
        projection=proj,
        hub=hub,
        trust=DEFAULT_TRUST,
        now=datetime(2026, 2, 2, tzinfo=UTC),
    )
    assert report2.changes == 0
