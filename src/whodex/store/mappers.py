from __future__ import annotations

from datetime import UTC, datetime

from whodex.domain.enums import InteractionKind, ObsOp, UserActionType
from whodex.domain.events import Interaction, Observation, UserAction
from whodex.store.rows import InteractionRow, ObservationRow, UserActionRow


def _utc(dt: datetime) -> datetime:
    """Restore UTC tzinfo stripped by SQLite's naive datetime storage."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def obs_to_row(o: Observation) -> ObservationRow:
    return ObservationRow(**{**o.model_dump(), "op": o.op.value})


def row_to_obs(r: ObservationRow) -> Observation:
    data = r.model_dump()
    data["op"] = ObsOp(data["op"])
    data["observed_at"] = _utc(data["observed_at"])
    data["ingested_at"] = _utc(data["ingested_at"])
    return Observation(**data)


def interaction_to_row(i: Interaction) -> InteractionRow:
    d = i.model_dump()
    d["kind"] = i.kind.value
    d["participant_ids"] = list(i.participant_ids)
    return InteractionRow(**d)


def row_to_interaction(r: InteractionRow) -> Interaction:
    d = r.model_dump()
    d["kind"] = InteractionKind(d["kind"])
    d["participant_ids"] = tuple(d["participant_ids"] or ())
    d["occurred_at"] = _utc(d["occurred_at"])
    d["created_at"] = _utc(d["created_at"])
    return Interaction(**d)


def action_to_row(a: UserAction) -> UserActionRow:
    return UserActionRow(**{**a.model_dump(), "action_type": a.action_type.value})


def row_to_action(r: UserActionRow) -> UserAction:
    d = r.model_dump()
    d["action_type"] = UserActionType(d["action_type"])
    d["created_at"] = _utc(d["created_at"])
    return UserAction(**d)
