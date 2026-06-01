from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
