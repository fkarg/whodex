from __future__ import annotations

import contextlib
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from whodex.domain.enums import EntityKind, UserActionType
from whodex.domain.fields import field_def, is_valid_field
from whodex.domain.state import Change, EntityGraphState, EventStream


class ScoreInput(BaseModel):
    entity_id: str
    display_name: str | None
    last_interaction_at: datetime | None
    cadence_days: int
    tier: str
    pinned: bool = False
    snoozed_until: datetime | None = None
    open_change_kinds: tuple[str, ...] = ()


class Score(BaseModel):
    value: float
    reasons: list[str] = Field(default_factory=list)


def _default_tier_weight() -> dict[str, float]:
    return {"inner": 2.0, "close": 1.3, "loose": 1.0}


def _default_cadence() -> dict[str, int]:
    return {"inner": 30, "close": 90, "loose": 180}


def _default_event_weight() -> dict[str, float]:
    return {"job.title": 1.0, "job.org": 1.0, "person.organisations": 1.0, "person.lives": 0.7}


class ScoringConfig(BaseModel):
    w_overdue: float = 1.0
    w_event: float = 0.5
    overdue_cap: float = 3.0
    pin_floor: float = 1000.0
    reminder_threshold: float = 1.0
    tier_weight: dict[str, float] = Field(default_factory=_default_tier_weight)
    cadence_default: dict[str, int] = Field(default_factory=_default_cadence)
    event_weight: dict[str, float] = Field(default_factory=_default_event_weight)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _coerce_cadence(value: object, default: int) -> int:
    if isinstance(value, bool):  # bool is an int subclass — reject
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return default


def score_contact(si: ScoreInput, cfg: ScoringConfig, now: datetime) -> Score:
    """Pure, explainable rank. Higher = reach out sooner. Snoozed => -inf (excluded)."""
    if si.snoozed_until is not None and si.snoozed_until > now:
        return Score(value=float("-inf"), reasons=["snoozed"])

    reasons: list[str] = []
    if si.last_interaction_at is None:
        overdue_ratio = cfg.overdue_cap
        reasons.append("never contacted")
    else:
        days = (now - si.last_interaction_at).days
        overdue_ratio = days / si.cadence_days if si.cadence_days > 0 else 0.0
        reasons.append(f"{overdue_ratio:.1f}x overdue ({days}d / {si.cadence_days}d cadence)")
    overdue_ratio = _clamp(overdue_ratio, 0.0, cfg.overdue_cap)

    event_boost = sum(cfg.event_weight.get(k, 0.5) for k in si.open_change_kinds)
    if event_boost:
        reasons.append(f"recent change ({', '.join(si.open_change_kinds)})")

    tier_weight = cfg.tier_weight.get(si.tier, 1.0)
    base = (cfg.w_overdue * overdue_ratio + cfg.w_event * event_boost) * tier_weight
    if si.tier != "loose":
        reasons.append(f"tier={si.tier}")

    value = base
    if si.pinned:
        value = max(base, cfg.pin_floor)
        reasons.append("pinned")
    return Score(value=value, reasons=reasons)


def _latest_interaction(entity_id: str, events: EventStream) -> datetime | None:
    times = [i.occurred_at for i in events.interactions if entity_id in i.participant_ids]
    return max(times) if times else None


def _pin_and_snooze(entity_id: str, events: EventStream) -> tuple[bool, datetime | None]:
    pinned = False
    snoozed_until: datetime | None = None
    for a in sorted(events.user_actions, key=lambda x: x.created_at):
        if a.entity_id != entity_id:
            continue
        if a.action_type == UserActionType.pin and a.target_type == "contact":
            pinned = True
        elif a.action_type == UserActionType.unpin and a.target_type == "contact":
            pinned = False
        elif a.action_type == UserActionType.snooze:
            raw = a.payload.get("until")
            if raw is not None:
                with contextlib.suppress(ValueError, TypeError):
                    snoozed_until = datetime.fromisoformat(str(raw))
    return pinned, snoozed_until


def build_score_inputs(
    states: EntityGraphState,
    events: EventStream,
    *,
    cfg: ScoringConfig,
    now: datetime,
    open_changes: Sequence[Change] = (),
) -> list[ScoreInput]:
    inputs: list[ScoreInput] = []
    for entity_id, state in states.items():
        if state.kind != EntityKind.person:
            continue
        tier_fv = state.fields.get("person.importance")
        tier = str(tier_fv.value) if tier_fv and str(tier_fv.value) in cfg.tier_weight else "loose"
        cad_fv = state.fields.get("person.cadence_days")
        cadence_days = (
            _coerce_cadence(cad_fv.value, cfg.cadence_default[tier])
            if cad_fv is not None
            else cfg.cadence_default[tier]
        )
        pinned, snoozed_until = _pin_and_snooze(entity_id, events)
        # Gather un-acked notable (volatile) open changes for this person.
        eid = entity_id
        notable_kinds = tuple(
            c.field
            for c in open_changes
            if c.entity_id == eid
            and not c.seen
            and is_valid_field(c.field)
            and field_def(c.field).volatile
        )
        inputs.append(
            ScoreInput(
                entity_id=entity_id,
                display_name=state.display_name,
                last_interaction_at=_latest_interaction(entity_id, events),
                cadence_days=cadence_days,
                tier=tier,
                pinned=pinned,
                snoozed_until=snoozed_until,
                open_change_kinds=notable_kinds,
            )
        )
    return inputs
