from datetime import UTC, datetime

from whodex.domain.enums import ReminderReason
from whodex.domain.ids import SequentialIdFactory
from whodex.engine.reminders import generate_reminders
from whodex.engine.scoring import Score, ScoreInput

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _si(eid):
    return ScoreInput(
        entity_id=eid, display_name=eid, last_interaction_at=None, cadence_days=30, tier="loose"
    )


def test_reminder_generated_above_threshold():
    scored = [(_si("E1"), Score(value=3.0, reasons=["3.0x overdue"]))]
    rems = generate_reminders(scored, ids=SequentialIdFactory("REM"), now=NOW, threshold=1.0)
    assert len(rems) == 1
    assert rems[0].entity_id == "E1"
    assert rems[0].reason == ReminderReason.cadence_lapsed
    assert rems[0].why == ["3.0x overdue"]


def test_below_threshold_and_snoozed_excluded():
    scored = [
        (_si("E1"), Score(value=0.2, reasons=["0.2x overdue"])),
        (_si("E2"), Score(value=float("-inf"), reasons=["snoozed"])),
    ]
    rems = generate_reminders(scored, ids=SequentialIdFactory("REM"), now=NOW, threshold=1.0)
    assert rems == []


def test_fingerprint_is_stable_for_same_situation():
    scored = [(_si("E1"), Score(value=3.0, reasons=["3.0x overdue"]))]
    a = generate_reminders(scored, ids=SequentialIdFactory("REM"), now=NOW, threshold=1.0)[0]
    b = generate_reminders(scored, ids=SequentialIdFactory("REM"), now=NOW, threshold=1.0)[0]
    assert a.fingerprint == b.fingerprint
