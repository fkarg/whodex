from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from whodex.domain.enums import EdgeType, EntityKind, ReminderReason, Significance, SuggestionStatus
from whodex.domain.events import Interaction, Observation, UserAction


class FieldValue(BaseModel):
    field: str
    value: Any
    source_kind: str
    observed_at: datetime
    ingested_at: datetime
    pinned: bool = False


class EntityState(BaseModel):
    entity_id: str
    kind: EntityKind
    display_name: str | None = None
    fields: dict[str, FieldValue] = Field(default_factory=dict)


class ContactProfileState(BaseModel):
    entity_id: str
    job_title: str | None = None
    primary_email: str | None = None
    linkedin_url: str | None = None
    last_interaction_at: datetime | None = None


class Change(BaseModel):
    id: str
    entity_id: str
    field: str
    old_value: Any = None
    new_value: Any = None
    caused_by_observation: str
    detected_at: datetime
    significance: Significance = Significance.minor
    # Stable dedup key: sha256(entity_id | field | canonical(new_value)).
    # Added in Phase 1c for user-state overlay across re-syncs.
    fingerprint: str = ""
    seen: bool = False
    notified: bool = False


class ConflictSuggestion(BaseModel):
    id: str
    entity_id: str
    field: str
    winning_observation_id: str
    disagreeing_observation_id: str
    reason: str
    fingerprint: str
    detected_at: datetime
    status: SuggestionStatus = SuggestionStatus.open


class Reminder(BaseModel):
    id: str
    entity_id: str
    due_at: datetime
    reason: ReminderReason
    fingerprint: str  # hash of (entity, sorted reasons) — anti-spam dedup key
    score: float
    why: list[str]
    created_at: datetime


class GraphRepairSuggestion(BaseModel):  # seam only in Phase 0
    id: str
    repair_type: str
    src_entity_id: str | None = None
    dst_entity_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str
    detected_at: datetime
    status: SuggestionStatus = SuggestionStatus.open


class Edge(BaseModel):  # seam only in Phase 0
    id: str
    src_entity_id: str
    dst_entity_id: str
    type: EdgeType
    weight: float = 1.0
    observed_at: datetime | None = None


class EventStream(BaseModel):
    observations: list[Observation] = Field(default_factory=list)
    interactions: list[Interaction] = Field(default_factory=list)
    user_actions: list[UserAction] = Field(default_factory=list)


EntityGraphState = dict[str, EntityState]


class ProjectionResult(BaseModel):
    states: EntityGraphState = Field(default_factory=dict)
    changes: list[Change] = Field(default_factory=list)
    conflict_suggestions: list[ConflictSuggestion] = Field(default_factory=list)
    graph_repairs: list[GraphRepairSuggestion] = Field(default_factory=list)


class VaultFileState(BaseModel):
    """Persisted tracking state for a single vault file.

    Attributes:
        path: Relative vault path, e.g. ``"People/Jane.md"``. Primary key.
        last_content_hash: SHA-256 hex digest of the last-seen full file content.
        last_frontmatter_seen: Parsed frontmatter dict at time of last read.
        last_mtime: File modification time (seconds since epoch) at last scan.
        last_written_hash: SHA-256 hex digest of content whodex last wrote,
            or ``None`` if whodex has never written to this file.
    """

    path: str
    last_content_hash: str
    last_frontmatter_seen: dict[str, Any] = Field(default_factory=dict)
    last_mtime: float
    last_written_hash: str | None = None
