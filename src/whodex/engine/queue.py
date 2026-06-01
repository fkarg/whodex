from __future__ import annotations

from datetime import datetime

from whodex.domain.state import EntityGraphState, EventStream
from whodex.engine.scoring import (
    Score,
    ScoreInput,
    ScoringConfig,
    build_score_inputs,
    score_contact,
)


def priority_queue(
    states: EntityGraphState, events: EventStream, *, cfg: ScoringConfig, now: datetime
) -> list[tuple[ScoreInput, Score]]:
    """Ranked (ScoreInput, Score) pairs, highest first, excluding snoozed (-inf)."""
    scored = [
        (si, score_contact(si, cfg, now))
        for si in build_score_inputs(states, events, cfg=cfg, now=now)
    ]
    live = [(si, sc) for si, sc in scored if sc.value != float("-inf")]
    live.sort(key=lambda pair: pair[1].value, reverse=True)
    return live
