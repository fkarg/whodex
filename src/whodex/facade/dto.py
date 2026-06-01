"""Pure data-transfer objects for the Whodex facade.

These are all pydantic BaseModel subclasses with no dependencies on internal
store or engine types — safe to expose to any front-end (TUI, HTTP, CLI).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FieldEntry(BaseModel):
    """Per-field value with freshness and source metadata."""

    value: Any
    source_kind: str
    observed_at: datetime
    staleness: str = "fresh"  # "fresh" | "stale" | "expired"


class TimelineEntry(BaseModel):
    """A single item in a contact's interleaved timeline."""

    kind: str  # "interaction" | "change"
    occurred_at: datetime
    summary: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class RankedContact(BaseModel):
    """A contact in the priority queue, with score and explainability."""

    entity_id: str
    display_name: str | None
    score: float
    why: list[str]
    tier: str
    last_interaction_at: datetime | None


class ContactDetail(BaseModel):
    """Full detail view of a single contact."""

    entity_id: str
    display_name: str | None
    kind: str
    fields: dict[str, FieldEntry] = Field(default_factory=dict)
    contact_points: list[str] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    open_changes: list[dict[str, Any]] = Field(default_factory=list)


class ReviewItem(BaseModel):
    """A single item in the review queue (conflict, repair, etc.)."""

    kind: str  # "conflict" | "repair"
    id: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
