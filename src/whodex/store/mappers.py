from __future__ import annotations

from datetime import UTC, datetime

from whodex.domain.enums import (
    EdgeType,
    EntityKind,
    InteractionKind,
    ObsOp,
    ReminderReason,
    Significance,
    SuggestionStatus,
    UserActionType,
)
from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.state import (
    Change,
    ConflictSuggestion,
    Edge,
    GraphRepairSuggestion,
    Notification,
    Reminder,
    VaultFileState,
)
from whodex.store.rows import (
    ChangeRow,
    ConflictSuggestionRow,
    EdgeRow,
    EntityRow,
    GraphRepairSuggestionRow,
    InteractionRow,
    NotificationRow,
    ObservationRow,
    ReminderRow,
    UserActionRow,
    VaultFileStateRow,
)


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


def restore_entity_row(r: EntityRow) -> EntityRow:
    """Return a copy of *r* with tz-aware ``created_at`` (SQLite strips tzinfo)."""
    if r.created_at.tzinfo is None:
        return r.model_copy(update={"created_at": _utc(r.created_at)})
    return r


def entity_row_kind(r: EntityRow) -> EntityKind:
    return EntityKind(r.kind)


def edge_to_row(e: Edge) -> EdgeRow:
    return EdgeRow(
        id=e.id,
        src_entity_id=e.src_entity_id,
        dst_entity_id=e.dst_entity_id,
        type=e.type.value,
        weight=e.weight,
        observed_at=e.observed_at,
    )


def row_to_edge(r: EdgeRow) -> Edge:
    d = r.model_dump()
    d["type"] = EdgeType(d["type"])
    if d.get("observed_at") is not None:
        d["observed_at"] = _utc(d["observed_at"])
    return Edge(**d)


def change_to_row(c: Change) -> ChangeRow:
    return ChangeRow(
        id=c.id,
        entity_id=c.entity_id,
        field=c.field,
        old_value=c.old_value,
        new_value=c.new_value,
        caused_by_observation=c.caused_by_observation,
        detected_at=c.detected_at,
        significance=c.significance.value,
        fingerprint=c.fingerprint,
        seen=c.seen,
        notified=c.notified,
    )


def row_to_change(r: ChangeRow) -> Change:
    d = r.model_dump()
    d["significance"] = Significance(d["significance"])
    d["detected_at"] = _utc(d["detected_at"])
    return Change(**d)


def conflict_to_row(c: ConflictSuggestion) -> ConflictSuggestionRow:
    return ConflictSuggestionRow(
        id=c.id,
        entity_id=c.entity_id,
        field=c.field,
        winning_observation_id=c.winning_observation_id,
        disagreeing_observation_id=c.disagreeing_observation_id,
        reason=c.reason,
        fingerprint=c.fingerprint,
        detected_at=c.detected_at,
        status=c.status.value,
    )


def row_to_conflict(r: ConflictSuggestionRow) -> ConflictSuggestion:
    d = r.model_dump()
    d["status"] = SuggestionStatus(d["status"])
    d["detected_at"] = _utc(d["detected_at"])
    return ConflictSuggestion(**d)


def repair_to_row(g: GraphRepairSuggestion) -> GraphRepairSuggestionRow:
    return GraphRepairSuggestionRow(
        id=g.id,
        repair_type=g.repair_type,
        src_entity_id=g.src_entity_id,
        dst_entity_id=g.dst_entity_id,
        payload=g.payload,
        fingerprint=g.fingerprint,
        detected_at=g.detected_at,
        status=g.status.value,
    )


def row_to_repair(r: GraphRepairSuggestionRow) -> GraphRepairSuggestion:
    d = r.model_dump()
    d["status"] = SuggestionStatus(d["status"])
    d["detected_at"] = _utc(d["detected_at"])
    if d.get("payload") is None:
        d["payload"] = {}
    return GraphRepairSuggestion(**d)


def reminder_to_row(rem: Reminder) -> ReminderRow:
    return ReminderRow(
        id=rem.id,
        entity_id=rem.entity_id,
        due_at=rem.due_at,
        reason=rem.reason.value,
        fingerprint=rem.fingerprint,
        score=rem.score,
        why=rem.why,
        created_at=rem.created_at,
    )


def row_to_reminder(r: ReminderRow) -> Reminder:
    d = r.model_dump()
    d["reason"] = ReminderReason(d["reason"])
    d["due_at"] = _utc(d["due_at"])
    d["created_at"] = _utc(d["created_at"])
    if d.get("why") is None:
        d["why"] = []
    return Reminder(**d)


def vault_state_to_row(v: VaultFileState) -> VaultFileStateRow:
    return VaultFileStateRow(
        path=v.path,
        last_content_hash=v.last_content_hash,
        last_frontmatter_seen=v.last_frontmatter_seen,
        last_mtime=v.last_mtime,
        last_written_hash=v.last_written_hash,
    )


def row_to_vault_state(r: VaultFileStateRow) -> VaultFileState:
    return VaultFileState(
        path=r.path,
        last_content_hash=r.last_content_hash,
        last_frontmatter_seen=r.last_frontmatter_seen or {},
        last_mtime=r.last_mtime,
        last_written_hash=r.last_written_hash,
    )


def notification_to_row(n: Notification) -> NotificationRow:
    return NotificationRow(
        id=n.id,
        kind=n.kind,
        entity_id=n.entity_id,
        payload=n.payload,
        dedupe_key=n.dedupe_key,
        created_at=n.created_at,
        delivered_to=list(n.delivered_to),
        state=n.state,
    )


def row_to_notification(r: NotificationRow) -> Notification:
    return Notification(
        id=r.id,
        kind=r.kind,
        entity_id=r.entity_id,
        payload=r.payload or {},
        dedupe_key=r.dedupe_key,
        created_at=_utc(r.created_at),
        delivered_to=list(r.delivered_to or []),
        state=r.state,
    )
