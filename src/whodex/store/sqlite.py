from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from whodex.domain.enums import EntityKind
from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.identity import normalize_identifier
from whodex.domain.ids import IdFactory
from whodex.domain.state import EventStream
from whodex.store import mappers
from whodex.store.rows import (
    EntityIdentifierRow,
    EntityRow,
    InteractionRow,
    ObservationRow,
    UserActionRow,
)


class SqliteLedgerStore:
    def __init__(self, url: str = "sqlite://") -> None:
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self._engine)

    def append_observations(self, observations: Sequence[Observation]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.obs_to_row(o) for o in observations])
            s.commit()

    def append_interactions(self, interactions: Sequence[Interaction]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.interaction_to_row(i) for i in interactions])
            s.commit()

    def append_user_actions(self, actions: Sequence[UserAction]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.action_to_row(a) for a in actions])
            s.commit()

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
                row = EntityIdentifierRow(
                    id=self._id_factory.new(),
                    entity_id=entity_id,
                    kind=kind,
                    value=normalised,
                )
                s.add(row)
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
