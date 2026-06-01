from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class ObservationRow(SQLModel, table=True):
    __tablename__ = "observation"
    id: str = Field(primary_key=True)
    source_run_id: str = Field(index=True)
    source_kind: str
    entity_id: str | None = Field(default=None, index=True)
    external_ref: str = Field(index=True)
    external_ref_kind: str
    field: str = Field(index=True)
    op: str
    value: Any = Field(default=None, sa_column=Column(JSON))
    value_hash: str = Field(index=True)
    observed_at: datetime = Field(index=True)
    ingested_at: datetime
    confidence: float = 1.0
    raw_ref: str | None = None


class InteractionRow(SQLModel, table=True):
    __tablename__ = "interaction"
    id: str = Field(primary_key=True)
    kind: str
    occurred_at: datetime
    participant_ids: Any = Field(default=None, sa_column=Column(JSON))
    summary: str | None = None
    source_run_id: str | None = None
    created_at: datetime


class UserActionRow(SQLModel, table=True):
    __tablename__ = "user_action"
    id: str = Field(primary_key=True)
    action_type: str
    target_type: str
    target_id: str = Field(index=True)
    entity_id: str | None = Field(default=None, index=True)
    payload: Any = Field(default=None, sa_column=Column(JSON))
    created_at: datetime
    actor: str = "user"


class EntityRow(SQLModel, table=True):
    __tablename__ = "entity"
    id: str = Field(primary_key=True)
    kind: str
    subtype: str | None = None
    created_at: datetime
    vault_path: str | None = Field(default=None, index=True)
    vault_uid: str | None = Field(default=None, index=True)
    merged_into: str | None = None
    archived: bool = False


class EntityIdentifierRow(SQLModel, table=True):
    __tablename__ = "entity_identifier"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_entity_identifier_kind_value"),)
    id: str = Field(primary_key=True)
    entity_id: str = Field(index=True)
    kind: str
    value: str


class ProjectionStateRow(SQLModel, table=True):
    __tablename__ = "projection_state"
    entity_id: str = Field(primary_key=True)
    state_json: str
