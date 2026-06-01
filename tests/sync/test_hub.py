from datetime import UTC, datetime

from tests.conftest import raw
from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.store.memory import InMemoryEntityStore, InMemoryLedgerStore
from whodex.sync.hub import IngestionHub, StoreIdentityResolver

_HUB_CLOCK = FixedClock(datetime(2026, 2, 1, tzinfo=UTC))


def _hub() -> IngestionHub:
    return IngestionHub(
        ids=SequentialIdFactory("OBS"),
        clock=_HUB_CLOCK,
        identity=StoreIdentityResolver(
            InMemoryEntityStore(SequentialIdFactory("E")),
            InMemoryLedgerStore(),
            ids=SequentialIdFactory("ACT"),
            clock=_HUB_CLOCK,
        ),
    )


def test_hub_resolves_new_entity_and_finalizes_observations():
    hub = _hub()
    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
    from whodex.sources.fake import FakeSource

    result = hub.ingest(FakeSource(records=[r]), r, source_run_id="RUN-1")
    # Entity IDs come from the EntityStore's SequentialIdFactory("E"), so first
    # entity will be "E-00000001".
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


# ---------------------------------------------------------------------------
# Interaction path
# ---------------------------------------------------------------------------


def test_hub_ingest_includes_interactions_from_source():
    """A source exposing interactions() → IngestResult.interactions has one entry."""
    from datetime import UTC, datetime

    from whodex.domain.enums import InteractionKind
    from whodex.domain.events import InteractionDraft

    HUB_CLOCK = FixedClock(datetime(2026, 2, 1, tzinfo=UTC))

    class SourceWithInteraction:
        id: str = "test_ia"
        capabilities = __import__("whodex.domain.enums", fromlist=["Capability"]).Capability.PULL
        identity_keys: tuple[str, ...] = ("email",)
        provides: tuple = ()

        def __init__(self, records, ia_drafts):
            self._records = records
            self._ia_drafts = ia_drafts

        def fetch(self, since):
            return list(self._records)

        def normalize(self, record):
            from whodex.sources.base import FieldMap, apply_map

            return apply_map(
                record,
                [FieldMap("display_name", "name.full")],
            )

        def interactions(self, record):
            return list(self._ia_drafts)

    occurred = datetime(2026, 2, 1, tzinfo=UTC)
    ia_draft = InteractionDraft(kind=InteractionKind.note, occurred_at=occurred)
    r = raw(identity={"email": "x@y.com"}, payload={"display_name": "Tester"})
    src = SourceWithInteraction(records=[r], ia_drafts=[ia_draft])

    hub = IngestionHub(
        ids=SequentialIdFactory("OBS"),
        clock=HUB_CLOCK,
        identity=StoreIdentityResolver(
            InMemoryEntityStore(SequentialIdFactory("E")),
            InMemoryLedgerStore(),
            ids=SequentialIdFactory("ACT"),
            clock=HUB_CLOCK,
        ),
    )

    result = hub.ingest(src, r, source_run_id="RUN-IA")
    assert len(result.interactions) == 1
    ia = result.interactions[0]
    assert ia.participant_ids == (result.entity_id,)
    assert ia.kind == InteractionKind.note
    assert ia.occurred_at == occurred


def test_hub_ingest_no_interactions_for_source_without_interactions_method():
    """Sources without an interactions() method yield an empty interactions list."""
    hub = _hub()
    from whodex.sources.fake import FakeSource

    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
    result = hub.ingest(FakeSource(records=[r]), r, source_run_id="RUN-1")
    assert result.interactions == []
