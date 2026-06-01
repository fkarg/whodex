from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from whodex.domain.events import Observation
from whodex.domain.state import FieldValue


def _sort_key(
    o: Observation, trust: Mapping[str, int]
) -> tuple[int, datetime, datetime, float, str]:
    return (
        trust.get(o.source_kind, 0),
        o.observed_at,
        o.ingested_at,
        o.confidence,
        o.id,
    )


def resolve_field(
    observations: Sequence[Observation],
    *,
    pinned: object | None,
    trust: Mapping[str, int],
) -> tuple[FieldValue, Observation | None, list[Observation]]:
    """Return (winning FieldValue, winning Observation|None, losing observations).

    Precedence (DESIGN §6.1): pin > trust > observed_at > ingested_at > confidence > id.
    A pin overlay (from a UserAction) beats every observation; the winner Observation is then None.
    """
    if not observations:
        raise ValueError("resolve_field requires at least one observation")
    ordered = sorted(observations, key=lambda o: _sort_key(o, trust))
    winner = ordered[-1]
    losers = ordered[:-1]
    if pinned is not None:
        fv = FieldValue(
            field=winner.field,
            value=pinned,
            source_kind="manual_cli",
            observed_at=winner.observed_at,
            ingested_at=winner.ingested_at,
            pinned=True,
        )
        return fv, None, list(observations)
    fv = FieldValue(
        field=winner.field,
        value=winner.value,
        source_kind=winner.source_kind,
        observed_at=winner.observed_at,
        ingested_at=winner.ingested_at,
        pinned=False,
    )
    return fv, winner, losers
