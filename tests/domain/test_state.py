from datetime import UTC, datetime

from whodex.domain.enums import EntityKind
from whodex.domain.state import EntityState, FieldValue, ProjectionResult


def test_entity_state_field_lookup():
    fv = FieldValue(
        field="job.title",
        value="Eng",
        source_kind="fake",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
        pinned=False,
    )
    s = EntityState(
        entity_id="E1", kind=EntityKind.person, display_name="Jane", fields={"job.title": fv}
    )
    assert s.fields["job.title"].value == "Eng"


def test_empty_projection_result():
    r = ProjectionResult()
    assert r.states == {}
    assert r.changes == []
    assert r.conflict_suggestions == []
    assert r.graph_repairs == []
