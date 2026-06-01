from tests.conftest import raw
from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.sync.hub import IdentityResolver, IngestionHub


def _hub():
    from datetime import UTC, datetime

    return IngestionHub(
        ids=SequentialIdFactory("OBS"),
        clock=FixedClock(datetime(2026, 2, 1, tzinfo=UTC)),
        identity=IdentityResolver(SequentialIdFactory("E")),
    )


def test_hub_resolves_new_entity_and_finalizes_observations():
    hub = _hub()
    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
    from whodex.sources.fake import FakeSource

    result = hub.ingest(FakeSource(records=[r]), r, source_run_id="RUN-1")
    assert result.entity_id == "E-00000001"
    assert all(o.entity_id == "E-00000001" for o in result.observations)
    assert all(o.ingested_at.year == 2026 for o in result.observations)
    assert {o.field for o in result.observations} == {"name.full", "job.title"}


def test_hub_reuses_entity_for_same_identity():
    hub = _hub()
    from whodex.sources.fake import FakeSource

    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane"})
    first = hub.ingest(FakeSource(records=[r]), r, source_run_id="RUN-1")
    second = hub.ingest(FakeSource(records=[r]), r, source_run_id="RUN-2")
    assert first.entity_id == second.entity_id
