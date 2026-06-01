from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from whodex.domain.enums import EntityKind
from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.identity import normalize_identifier
from whodex.domain.ids import IdFactory
from whodex.domain.state import EntityGraphState, EntityState, EventStream
from whodex.store import mappers
from whodex.store.rows import (
    EntityIdentifierRow,
    EntityRow,
    InteractionRow,
    ObservationRow,
    ProjectionStateRow,
    UserActionRow,
)


class SqliteLedgerStore:
    def __init__(self, url: str = "sqlite://", *, jsonl_dir: Path | None = None) -> None:
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self._jsonl_dir = jsonl_dir
        SQLModel.metadata.create_all(self._engine)

    def append_observations(self, observations: Sequence[Observation]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.obs_to_row(o) for o in observations])
            s.commit()
        if self._jsonl_dir is not None:
            from whodex.store.jsonl import append_jsonl

            append_jsonl(self._jsonl_dir, "observations", observations)

    def append_interactions(self, interactions: Sequence[Interaction]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.interaction_to_row(i) for i in interactions])
            s.commit()
        if self._jsonl_dir is not None:
            from whodex.store.jsonl import append_jsonl

            append_jsonl(self._jsonl_dir, "interactions", interactions)

    def append_user_actions(self, actions: Sequence[UserAction]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.action_to_row(a) for a in actions])
            s.commit()
        if self._jsonl_dir is not None:
            from whodex.store.jsonl import append_jsonl

            append_jsonl(self._jsonl_dir, "user_actions", actions)

    def read_events(self) -> EventStream:
        with Session(self._engine) as s:
            obs = [mappers.row_to_obs(r) for r in s.exec(select(ObservationRow)).all()]
            ints = [mappers.row_to_interaction(r) for r in s.exec(select(InteractionRow)).all()]
            acts = [mappers.row_to_action(r) for r in s.exec(select(UserActionRow)).all()]
        return EventStream(observations=obs, interactions=ints, user_actions=acts)


class SqliteEntityStore:
    """SQLite-backed EntityStore using the same StaticPool pattern as SqliteLedgerStore."""

    def __init__(self, url: str = "sqlite://", *, id_factory: IdFactory) -> None:
        self._id_factory = id_factory
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self._engine)

    def create_entity(
        self,
        kind: EntityKind,
        *,
        created_at: datetime,
        subtype: str | None = None,
        vault_path: str | None = None,
        vault_uid: str | None = None,
    ) -> str:
        eid = self._id_factory.new()
        row = EntityRow(
            id=eid,
            kind=kind.value,
            subtype=subtype,
            created_at=created_at,
            vault_path=vault_path,
            vault_uid=vault_uid,
        )
        with Session(self._engine) as s:
            s.add(row)
            s.commit()
        return eid

    def add_identifiers(self, entity_id: str, pairs: Sequence[tuple[str, str]]) -> None:
        with Session(self._engine) as s:
            for kind, value in pairs:
                normalised = normalize_identifier(kind, value)
                stmt = (
                    sqlite_insert(EntityIdentifierRow)
                    .values(
                        id=self._id_factory.new(),
                        entity_id=entity_id,
                        kind=kind,
                        value=normalised,
                    )
                    .on_conflict_do_nothing(index_elements=["kind", "value"])
                )
                s.exec(stmt)  # type: ignore[call-overload]
            s.commit()

    def find_by_identifiers(self, pairs: Sequence[tuple[str, str]]) -> str | None:
        with Session(self._engine) as s:
            for kind, value in pairs:
                normalised = normalize_identifier(kind, value)
                stmt = select(EntityIdentifierRow).where(
                    EntityIdentifierRow.kind == kind,
                    EntityIdentifierRow.value == normalised,
                )
                row = s.exec(stmt).first()
                if row is not None:
                    return row.entity_id
        return None

    def kinds(self) -> dict[str, EntityKind]:
        with Session(self._engine) as s:
            rows = s.exec(select(EntityRow)).all()
        return {r.id: EntityKind(r.kind) for r in rows}

    def get(self, entity_id: str) -> EntityRow | None:
        with Session(self._engine) as s:
            row = s.get(EntityRow, entity_id)
            if row is None:
                return None
            return mappers.restore_entity_row(row)


class SqliteProjectionStore:
    """SQLite-backed ProjectionStore. Each save() is a full snapshot (not an accumulation)."""

    def __init__(self, url: str = "sqlite://") -> None:
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self._engine)

    def save(self, states: EntityGraphState) -> None:
        with Session(self._engine) as s:
            # Delete all existing rows, then insert the new snapshot.
            existing = s.exec(select(ProjectionStateRow)).all()
            for row in existing:
                s.delete(row)
            for entity_id, entity_state in states.items():
                s.add(ProjectionStateRow(entity_id=entity_id, state_json=entity_state.model_dump_json()))
            s.commit()

    def load(self) -> EntityGraphState:
        with Session(self._engine) as s:
            rows = s.exec(select(ProjectionStateRow)).all()
        return {row.entity_id: EntityState.model_validate_json(row.state_json) for row in rows}
