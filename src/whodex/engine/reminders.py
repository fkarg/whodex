from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime

from whodex.domain.enums import ReminderReason
from whodex.domain.ids import IdFactory
from whodex.domain.state import Reminder
from whodex.engine.scoring import Score, ScoreInput


def _fingerprint(entity_id: str, reasons: list[str]) -> str:
    key = entity_id + "|" + "|".join(sorted(reasons))
    return hashlib.sha256(key.encode()).hexdigest()


def generate_reminders(
    scored: Sequence[tuple[ScoreInput, Score]],
    *,
    ids: IdFactory,
    now: datetime,
    threshold: float,
) -> list[Reminder]:
    """One reminder per contact at/above threshold; deterministic fingerprint per situation."""
    reminders: list[Reminder] = []
    for si, score in scored:
        if score.value < threshold:
            continue
        reminders.append(
            Reminder(
                id=ids.new(),
                entity_id=si.entity_id,
                due_at=now,
                reason=ReminderReason.cadence_lapsed,
                fingerprint=_fingerprint(si.entity_id, score.reasons),
                score=score.value,
                why=list(score.reasons),
                created_at=now,
            )
        )
    return reminders
