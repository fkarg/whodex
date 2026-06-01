"""Behavioural contract every ProjectionStore must satisfy. Subclass and override make_store."""

from __future__ import annotations

from datetime import UTC, datetime

from whodex.domain.enums import EntityKind
from whodex.domain.state import EntityState, FieldValue

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _state(eid: str, title: str) -> EntityState:
    fv = FieldValue(
        field="job.title",
        value=title,
        source_kind="obsidian",
        observed_at=NOW,
        ingested_at=NOW,
    )
    return EntityState(
        entity_id=eid,
        kind=EntityKind.person,
        display_name=eid,
        fields={"job.title": fv},
    )


class ProjectionStoreContract:
    def make_store(self):  # override -> returns a fresh ProjectionStore
        raise NotImplementedError

    def test_save_then_load_roundtrips(self) -> None:
        s = self.make_store()
        states = {"E1": _state("E1", "Eng")}
        s.save(states)
        assert s.load() == states

    def test_empty_load_is_empty(self) -> None:
        assert self.make_store().load() == {}

    def test_save_is_a_full_snapshot_not_accumulation(self) -> None:
        s = self.make_store()
        s.save({"E1": _state("E1", "Eng"), "E2": _state("E2", "PM")})
        s.save({"E1": _state("E1", "Staff Eng")})  # E2 dropped
        loaded = s.load()
        assert set(loaded) == {"E1"}
        assert loaded["E1"].fields["job.title"].value == "Staff Eng"
