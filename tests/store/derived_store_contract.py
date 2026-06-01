"""Behavioural contract every DerivedStore must satisfy. Subclass and override make_store."""

from __future__ import annotations

from datetime import UTC, datetime

from whodex.domain.enums import ReminderReason, Significance, SuggestionStatus
from whodex.domain.state import Change, ConflictSuggestion, GraphRepairSuggestion, Reminder

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _change(
    entity: str = "E1",
    field: str = "job.title",
    new_value: object = "Engineer",
    fingerprint: str = "fp-change-1",
    seen: bool = False,
    notified: bool = False,
) -> Change:
    return Change(
        id=f"CHG-{fingerprint}",
        entity_id=entity,
        field=field,
        old_value=None,
        new_value=new_value,
        caused_by_observation="OBS-001",
        detected_at=_T0,
        significance=Significance.notable,
        fingerprint=fingerprint,
        seen=seen,
        notified=notified,
    )


def _conflict(
    entity: str = "E1",
    field: str = "email",
    fingerprint: str = "fp-conflict-1",
    status: SuggestionStatus = SuggestionStatus.open,
) -> ConflictSuggestion:
    return ConflictSuggestion(
        id=f"CON-{fingerprint}",
        entity_id=entity,
        field=field,
        winning_observation_id="OBS-WIN",
        disagreeing_observation_id="OBS-LOSE",
        reason="lower_trust_disagrees",
        fingerprint=fingerprint,
        detected_at=_T0,
        status=status,
    )


def _repair(
    repair_type: str = "merge_candidate",
    fingerprint: str = "fp-repair-1",
    status: SuggestionStatus = SuggestionStatus.open,
) -> GraphRepairSuggestion:
    return GraphRepairSuggestion(
        id=f"REP-{fingerprint}",
        repair_type=repair_type,
        src_entity_id="E1",
        dst_entity_id="E2",
        payload={"reason": "same name"},
        fingerprint=fingerprint,
        detected_at=_T0,
        status=status,
    )


def _reminder(
    entity: str = "E1",
    fingerprint: str = "fp-reminder-1",
) -> Reminder:
    return Reminder(
        id=f"REM-{fingerprint}",
        entity_id=entity,
        due_at=_T0,
        reason=ReminderReason.cadence_lapsed,
        fingerprint=fingerprint,
        score=0.8,
        why=["no contact in 90 days"],
        created_at=_T0,
    )


class DerivedStoreContract:
    def make_store(self):  # override -> returns a fresh DerivedStore
        raise NotImplementedError

    # ── round-trip: save then read ────────────────────────────────────────────

    def test_changes_round_trip(self) -> None:
        s = self.make_store()
        c = _change()
        s.replace_changes([c])
        result = s.changes()
        assert len(result) == 1
        r = result[0]
        assert r.id == c.id
        assert r.entity_id == c.entity_id
        assert r.field == c.field
        assert r.new_value == c.new_value
        assert r.significance == c.significance
        assert r.fingerprint == c.fingerprint
        assert r.seen == False  # noqa: E712
        assert r.notified == False  # noqa: E712

    def test_conflicts_round_trip(self) -> None:
        s = self.make_store()
        c = _conflict()
        s.replace_conflicts([c])
        result = s.conflicts()
        assert len(result) == 1
        r = result[0]
        assert r.id == c.id
        assert r.fingerprint == c.fingerprint
        assert r.status == SuggestionStatus.open

    def test_repairs_round_trip(self) -> None:
        s = self.make_store()
        rep = _repair()
        s.replace_repairs([rep])
        result = s.repairs()
        assert len(result) == 1
        r = result[0]
        assert r.id == rep.id
        assert r.repair_type == rep.repair_type
        assert r.fingerprint == rep.fingerprint
        assert r.payload == rep.payload
        assert r.status == SuggestionStatus.open

    def test_reminders_round_trip(self) -> None:
        s = self.make_store()
        rem = _reminder()
        s.replace_reminders([rem])
        result = s.reminders()
        assert len(result) == 1
        r = result[0]
        assert r.id == rem.id
        assert r.entity_id == rem.entity_id
        assert r.reason == rem.reason
        assert r.why == rem.why
        assert r.fingerprint == rem.fingerprint

    def test_empty_store_returns_empty_lists(self) -> None:
        s = self.make_store()
        assert s.changes() == []
        assert s.conflicts() == []
        assert s.repairs() == []
        assert s.reminders() == []

    # ── snapshot: replacing with fewer items drops the old ───────────────────

    def test_replace_changes_with_fewer_drops_old(self) -> None:
        s = self.make_store()
        c1 = _change(fingerprint="fp-a", field="job.title")
        c2 = _change(fingerprint="fp-b", field="email", new_value="x@y.com")
        s.replace_changes([c1, c2])
        assert len(s.changes()) == 2
        s.replace_changes([c1])
        assert len(s.changes()) == 1
        assert s.changes()[0].fingerprint == "fp-a"

    def test_replace_conflicts_with_fewer_drops_old(self) -> None:
        s = self.make_store()
        s.replace_conflicts([_conflict(fingerprint="fp-a"), _conflict(fingerprint="fp-b")])
        assert len(s.conflicts()) == 2
        s.replace_conflicts([_conflict(fingerprint="fp-a")])
        assert len(s.conflicts()) == 1

    def test_replace_repairs_with_fewer_drops_old(self) -> None:
        s = self.make_store()
        s.replace_repairs([_repair(fingerprint="fp-a"), _repair(fingerprint="fp-b")])
        assert len(s.repairs()) == 2
        s.replace_repairs([_repair(fingerprint="fp-a")])
        assert len(s.repairs()) == 1

    def test_replace_reminders_with_fewer_drops_old(self) -> None:
        s = self.make_store()
        s.replace_reminders([_reminder(fingerprint="fp-a"), _reminder(fingerprint="fp-b")])
        assert len(s.reminders()) == 2
        s.replace_reminders([_reminder(fingerprint="fp-a")])
        assert len(s.reminders()) == 1

    def test_replace_empty_drops_all(self) -> None:
        s = self.make_store()
        s.replace_changes([_change()])
        s.replace_conflicts([_conflict()])
        s.replace_repairs([_repair()])
        s.replace_reminders([_reminder()])
        s.replace_changes([])
        s.replace_conflicts([])
        s.replace_repairs([])
        s.replace_reminders([])
        assert s.changes() == []
        assert s.conflicts() == []
        assert s.repairs() == []
        assert s.reminders() == []

    # ── overlay invariant: user-state survives a re-sync ─────────────────────

    def test_change_seen_preserved_across_resync(self) -> None:
        """A Change marked seen=True stays seen after replace_changes with same fingerprint."""
        s = self.make_store()
        fp = "fp-overlay"
        c = _change(fingerprint=fp)
        s.replace_changes([c])
        # Simulate: user acknowledges — set seen via acked_fingerprints on next replace
        s.replace_changes([c], acked_fingerprints={fp})
        result = s.changes()
        assert len(result) == 1
        assert result[0].seen is True

    def test_change_seen_persists_on_subsequent_resync(self) -> None:
        """Once seen, stays seen even without acked_fingerprints on the next replace."""
        s = self.make_store()
        fp = "fp-persist"
        c = _change(fingerprint=fp)
        # First replace acks it
        s.replace_changes([c], acked_fingerprints={fp})
        # Second replace — no acked_fingerprints supplied
        s.replace_changes([c])
        result = s.changes()
        assert len(result) == 1
        assert result[0].seen is True

    def test_conflict_dismissed_preserved_across_resync(self) -> None:
        """A ConflictSuggestion dismissed stays dismissed after replace."""
        s = self.make_store()
        fp = "fp-conflict-dismiss"
        c = _conflict(fingerprint=fp)
        s.replace_conflicts([c])
        s.replace_conflicts([c], dismissed_fingerprints={fp})
        result = s.conflicts()
        assert len(result) == 1
        assert result[0].status == SuggestionStatus.dismissed

    def test_conflict_dismissed_persists_on_subsequent_resync(self) -> None:
        s = self.make_store()
        fp = "fp-conflict-persist"
        c = _conflict(fingerprint=fp)
        s.replace_conflicts([c], dismissed_fingerprints={fp})
        s.replace_conflicts([c])
        result = s.conflicts()
        assert len(result) == 1
        assert result[0].status == SuggestionStatus.dismissed

    def test_repair_dismissed_preserved_across_resync(self) -> None:
        s = self.make_store()
        fp = "fp-repair-dismiss"
        r = _repair(fingerprint=fp)
        s.replace_repairs([r])
        s.replace_repairs([r], dismissed_fingerprints={fp})
        result = s.repairs()
        assert len(result) == 1
        assert result[0].status == SuggestionStatus.dismissed

    def test_repair_dismissed_persists_on_subsequent_resync(self) -> None:
        s = self.make_store()
        fp = "fp-repair-persist"
        r = _repair(fingerprint=fp)
        s.replace_repairs([r], dismissed_fingerprints={fp})
        s.replace_repairs([r])
        result = s.repairs()
        assert len(result) == 1
        assert result[0].status == SuggestionStatus.dismissed

    def test_new_fingerprint_not_affected_by_acked_set(self) -> None:
        """A new Change fingerprint not in acked_fingerprints stays unseen."""
        s = self.make_store()
        c = _change(fingerprint="fp-new")
        s.replace_changes([c], acked_fingerprints={"fp-other"})
        result = s.changes()
        assert len(result) == 1
        assert result[0].seen is False
