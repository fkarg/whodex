from datetime import UTC, datetime

from whodex.domain.enums import ReminderReason
from whodex.domain.state import Reminder


def test_reminder_construction():
    r = Reminder(
        id="REM-1",
        entity_id="E1",
        due_at=datetime(2026, 2, 1, tzinfo=UTC),
        reason=ReminderReason.cadence_lapsed,
        fingerprint="fp",
        score=2.5,
        why=["3.0x overdue"],
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert r.reason == ReminderReason.cadence_lapsed
    assert r.why == ["3.0x overdue"]
