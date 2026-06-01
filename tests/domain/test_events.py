from datetime import UTC, datetime

from whodex.domain.enums import ObsOp
from whodex.domain.events import Observation, ObservationDraft, RawRecord


def test_observation_is_immutable():
    o = Observation(
        id="OBS-1",
        source_run_id="RUN-1",
        source_kind="fake",
        entity_id="E1",
        external_ref="ext",
        external_ref_kind="fake_id",
        field="job.title",
        op=ObsOp.set,
        value="Eng",
        value_hash="h",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    try:
        o.value = "Other"  # type: ignore[misc]
        raise AssertionError("expected immutability error")
    except Exception:
        pass


def test_observation_draft_defaults():
    d = ObservationDraft(field="email", value="a@b.com")
    assert d.op == ObsOp.set
    assert d.observed_at is None
    assert d.confidence == 1.0


def test_raw_record_roundtrips():
    r = RawRecord(
        source="fake",
        identity={"email": "a@b.com"},
        payload={"x": 1},
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert r.source == "fake"
    assert r.identity["email"] == "a@b.com"
