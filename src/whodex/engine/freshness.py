from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from whodex.domain.enums import Staleness


class FreshnessConfig(BaseModel):
    ttl_days: dict[str, int] = Field(default_factory=dict)
    grace_factor: float = 2.0


def staleness(field: str, ingested_at: datetime, cfg: FreshnessConfig, now: datetime) -> Staleness:
    ttl = cfg.ttl_days.get(field, 0)
    if ttl == 0:
        return Staleness.fresh
    age = (now - ingested_at).days
    if age < ttl:
        return Staleness.fresh
    return Staleness.stale if age < ttl * cfg.grace_factor else Staleness.expired
