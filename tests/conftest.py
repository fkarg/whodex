from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from whodex.domain.canonical import value_hash
from whodex.domain.enums import InteractionKind, ObsOp, UserActionType
from whodex.domain.events import Interaction, Observation, RawRecord, UserAction

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _t(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


_counter = {"n": 0}


def _id(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:04d}"


def obs(
    *,
    entity: str,
    field: str,
    value: Any,
    source: str = "fake",
    op: ObsOp = ObsOp.set,
    observed: datetime = T0,
    ingested: datetime | None = None,
    confidence: float = 1.0,
    ext: str | None = None,
) -> Observation:
    return Observation(
        id=_id("OBS"),
        source_run_id="RUN-TEST",
        source_kind=source,
        entity_id=entity,
        external_ref=ext or entity,
        external_ref_kind=f"{source}_id",
        field=field,
        op=op,
        value=value,
        value_hash=value_hash(field, op, value),
        observed_at=observed,
        ingested_at=ingested or observed,
        confidence=confidence,
    )


def interaction(
    *,
    entities: tuple[str, ...],
    kind: InteractionKind = InteractionKind.met,
    occurred: datetime = T0,
) -> Interaction:
    return Interaction(
        id=_id("INT"),
        kind=kind,
        occurred_at=occurred,
        participant_ids=entities,
        created_at=occurred,
    )


def action(
    *,
    action_type: UserActionType,
    target_type: str,
    target_id: str,
    entity: str | None = None,
    payload: dict[str, Any] | None = None,
    created: datetime = T0,
) -> UserAction:
    return UserAction(
        id=_id("ACT"),
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        entity_id=entity,
        payload=payload or {},
        created_at=created,
    )


def raw(
    *,
    source: str = "fake",
    identity: dict[str, str],
    payload: dict[str, Any] | None = None,
    observed: datetime = T0,
) -> RawRecord:
    return RawRecord(
        source=source,
        identity=identity,
        payload=payload or {},
        observed_at=observed,
    )
