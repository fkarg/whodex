from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from whodex.domain.enums import InteractionKind, ObsOp, UserActionType

__all__ = [
    "RawRecord",
    "ObservationDraft",
    "Observation",
    "InteractionDraft",
    "Interaction",
    "UserAction",
]

_FROZEN = ConfigDict(frozen=True)


class RawRecord(BaseModel):
    """Producer output BEFORE field-mapping; also the ingestion API wire shape."""

    source: str
    identity: dict[str, str]
    payload: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    capture_context: dict[str, Any] = Field(default_factory=dict)


class ObservationDraft(BaseModel):
    """Connector output. The hub turns drafts into persisted Observations."""

    field: str
    op: ObsOp = ObsOp.set
    value: Any = None
    observed_at: datetime | None = None
    confidence: float = 1.0


class Observation(BaseModel):
    model_config = _FROZEN

    id: str
    source_run_id: str
    source_kind: str  # immutable per run; trust looked up from this at projection time
    entity_id: str | None = None
    external_ref: str
    external_ref_kind: str
    field: str
    op: ObsOp = ObsOp.set
    value: Any = None
    value_hash: str
    observed_at: datetime
    ingested_at: datetime
    confidence: float = 1.0
    raw_ref: str | None = None


class InteractionDraft(BaseModel):
    """Connector output for an interaction; the hub finalizes into a persisted Interaction."""

    kind: InteractionKind
    occurred_at: datetime
    summary: str | None = None


class Interaction(BaseModel):
    model_config = _FROZEN

    id: str
    kind: InteractionKind
    occurred_at: datetime
    participant_ids: tuple[str, ...] = ()
    summary: str | None = None
    source_run_id: str | None = None
    created_at: datetime


class UserAction(BaseModel):
    model_config = _FROZEN

    id: str
    action_type: UserActionType
    target_type: str
    target_id: str
    entity_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    actor: str = "user"
