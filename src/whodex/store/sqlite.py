from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from whodex.domain.enums import EdgeType, EntityKind, SuggestionStatus
from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.identity import normalize_identifier
from whodex.domain.ids import IdFactory
from whodex.domain.state import (
    Change,
    ConflictSuggestion,
    Edge,
    EntityGraphState,
    EntityState,
    EventStream,
    GraphRepairSuggestion,
    Reminder,
    VaultFileState,
)
from whodex.domain.tokens import hash_token
from whodex.store import mappers
from whodex.store.rows import (
    ChangeRow,
    ConflictSuggestionRow,
    EdgeRow,
    EntityIdentifierRow,
    EntityRow,
    GraphRepairSuggestionRow,
    InteractionRow,
    ObservationRow,
    ProjectionStateRow,
    ReminderRow,
    TokenRow,
    UserActionRow,
    VaultFileStateRow,
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
                s.exec(stmt)
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
                s.add(
                    ProjectionStateRow(
                        entity_id=entity_id, state_json=entity_state.model_dump_json()
                    )
                )
            s.commit()

    def load(self) -> EntityGraphState:
        with Session(self._engine) as s:
            rows = s.exec(select(ProjectionStateRow)).all()
        return {row.entity_id: EntityState.model_validate_json(row.state_json) for row in rows}


class SqliteEdgeStore:
    """SQLite-backed EdgeStore. replace_edges() is a full snapshot (delete-all then insert)."""

    def __init__(self, url: str = "sqlite://") -> None:
        connect_args: dict[str, object] = {"check_same_thread": False}
        self._engine = create_engine(
            url,
            connect_args=connect_args,
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self._engine)

    def replace_edges(self, edges: Sequence[Edge]) -> None:
        with Session(self._engine) as s:
            # Bulk DELETE first so the unique constraint is clear before INSERTs.
            # Row-by-row s.delete() lets SQLAlchemy reorder operations and hit
            # the unique constraint on the second sync; a bulk statement avoids that.
            s.exec(sa_delete(EdgeRow))
            for e in edges:
                s.add(mappers.edge_to_row(e))
            s.commit()

    def outgoing(self, entity_id: str, type: EdgeType | None = None) -> list[Edge]:
        with Session(self._engine) as s:
            stmt = select(EdgeRow).where(EdgeRow.src_entity_id == entity_id)
            if type is not None:
                stmt = stmt.where(EdgeRow.type == type.value)
            rows = s.exec(stmt).all()
        return [mappers.row_to_edge(r) for r in rows]

    def incoming(self, entity_id: str, type: EdgeType | None = None) -> list[Edge]:
        with Session(self._engine) as s:
            stmt = select(EdgeRow).where(EdgeRow.dst_entity_id == entity_id)
            if type is not None:
                stmt = stmt.where(EdgeRow.type == type.value)
            rows = s.exec(stmt).all()
        return [mappers.row_to_edge(r) for r in rows]

    def all_edges(self) -> list[Edge]:
        with Session(self._engine) as s:
            rows = s.exec(select(EdgeRow)).all()
        return [mappers.row_to_edge(r) for r in rows]


class SqliteDerivedStore:
    """SQLite-backed DerivedStore. Full-snapshot semantics with user-state overlay."""

    def __init__(self, url: str = "sqlite://") -> None:
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self._engine)

    def replace_changes(
        self,
        changes: Sequence[Change],
        *,
        acked_fingerprints: set[str] | None = None,
    ) -> None:
        acked = acked_fingerprints or set()
        with Session(self._engine) as s:
            # Load existing user state keyed by fingerprint
            existing: dict[str, ChangeRow] = {
                r.fingerprint: r for r in s.exec(select(ChangeRow)).all()
            }
            for row in existing.values():
                s.delete(row)
            for c in changes:
                fp = c.fingerprint
                prev = existing.get(fp)
                seen = c.seen
                notified = c.notified
                if prev is not None and (prev.seen or prev.notified):
                    seen = prev.seen
                    notified = prev.notified
                elif fp in acked:
                    seen = True
                row = mappers.change_to_row(c)
                row.seen = seen
                row.notified = notified
                s.add(row)
            s.commit()

    def replace_conflicts(
        self,
        conflicts: Sequence[ConflictSuggestion],
        *,
        dismissed_fingerprints: set[str] | None = None,
    ) -> None:
        dismissed = dismissed_fingerprints or set()
        with Session(self._engine) as s:
            existing: dict[str, ConflictSuggestionRow] = {
                r.fingerprint: r for r in s.exec(select(ConflictSuggestionRow)).all()
            }
            for row in existing.values():
                s.delete(row)
            for c in conflicts:
                fp = c.fingerprint
                prev = existing.get(fp)
                status = c.status
                if prev is not None and prev.status != SuggestionStatus.open.value:
                    status = SuggestionStatus(prev.status)
                elif fp in dismissed:
                    status = SuggestionStatus.dismissed
                row = mappers.conflict_to_row(c)
                row.status = status.value
                s.add(row)
            s.commit()

    def replace_repairs(
        self,
        repairs: Sequence[GraphRepairSuggestion],
        *,
        dismissed_fingerprints: set[str] | None = None,
    ) -> None:
        dismissed = dismissed_fingerprints or set()
        with Session(self._engine) as s:
            existing: dict[str, GraphRepairSuggestionRow] = {
                r.fingerprint: r for r in s.exec(select(GraphRepairSuggestionRow)).all()
            }
            for row in existing.values():
                s.delete(row)
            for r in repairs:
                fp = r.fingerprint
                prev = existing.get(fp)
                status = r.status
                if prev is not None and prev.status != SuggestionStatus.open.value:
                    status = SuggestionStatus(prev.status)
                elif fp in dismissed:
                    status = SuggestionStatus.dismissed
                row = mappers.repair_to_row(r)
                row.status = status.value
                s.add(row)
            s.commit()

    def replace_reminders(self, reminders: Sequence[Reminder]) -> None:
        with Session(self._engine) as s:
            existing = s.exec(select(ReminderRow)).all()
            for row in existing:
                s.delete(row)
            for rem in reminders:
                s.add(mappers.reminder_to_row(rem))
            s.commit()

    def changes(self) -> list[Change]:
        with Session(self._engine) as s:
            rows = s.exec(select(ChangeRow)).all()
        return [mappers.row_to_change(r) for r in rows]

    def conflicts(self) -> list[ConflictSuggestion]:
        with Session(self._engine) as s:
            rows = s.exec(select(ConflictSuggestionRow)).all()
        return [mappers.row_to_conflict(r) for r in rows]

    def repairs(self) -> list[GraphRepairSuggestion]:
        with Session(self._engine) as s:
            rows = s.exec(select(GraphRepairSuggestionRow)).all()
        return [mappers.row_to_repair(r) for r in rows]

    def reminders(self) -> list[Reminder]:
        with Session(self._engine) as s:
            rows = s.exec(select(ReminderRow)).all()
        return [mappers.row_to_reminder(r) for r in rows]


class SqliteVaultStateStore:
    """SQLite-backed VaultStateStore. put() is an upsert keyed on path."""

    def __init__(self, url: str = "sqlite://") -> None:
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self._engine)

    def get(self, path: str) -> VaultFileState | None:
        with Session(self._engine) as s:
            row = s.get(VaultFileStateRow, path)
            if row is None:
                return None
            return mappers.row_to_vault_state(row)

    def put(self, state: VaultFileState) -> None:
        stmt = (
            sqlite_insert(VaultFileStateRow)
            .values(
                path=state.path,
                last_content_hash=state.last_content_hash,
                last_frontmatter_seen=state.last_frontmatter_seen,
                last_mtime=state.last_mtime,
                last_written_hash=state.last_written_hash,
            )
            .on_conflict_do_update(
                index_elements=["path"],
                set_={
                    "last_content_hash": state.last_content_hash,
                    "last_frontmatter_seen": state.last_frontmatter_seen,
                    "last_mtime": state.last_mtime,
                    "last_written_hash": state.last_written_hash,
                },
            )
        )
        with Session(self._engine) as s:
            s.exec(stmt)
            s.commit()

    def all(self) -> list[VaultFileState]:
        with Session(self._engine) as s:
            rows = s.exec(select(VaultFileStateRow)).all()
        return [mappers.row_to_vault_state(r) for r in rows]


class SqliteTokenStore:
    """SQLite-backed TokenStore.  Only the SHA-256 hash of each token is persisted."""

    def __init__(self, url: str = "sqlite://", *, id_factory: IdFactory) -> None:
        self._id_factory = id_factory
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self._engine)

    def issue(self, label: str, *, token: str, created_at: datetime) -> str:
        token_id = self._id_factory.new()
        row = TokenRow(
            id=token_id,
            token_hash=hash_token(token),
            label=label,
            created_at=created_at,
            revoked=False,
        )
        with Session(self._engine) as s:
            s.add(row)
            s.commit()
        return token_id

    def validate(self, token: str) -> bool:
        h = hash_token(token)
        with Session(self._engine) as s:
            stmt = select(TokenRow).where(
                TokenRow.token_hash == h,
                TokenRow.revoked == False,  # noqa: E712
            )
            row = s.exec(stmt).first()
        return row is not None

    def revoke(self, token_id: str) -> None:
        with Session(self._engine) as s:
            row = s.get(TokenRow, token_id)
            if row is not None:
                row.revoked = True
                s.add(row)
                s.commit()

    def list_tokens(self) -> list[TokenRow]:
        with Session(self._engine) as s:
            rows = s.exec(select(TokenRow)).all()
        return list(rows)
