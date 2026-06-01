from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from whodex.domain.enums import EdgeType, EntityKind
from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.identity import normalize_identifier
from whodex.domain.ids import IdFactory
from whodex.domain.state import Edge, EntityGraphState, EventStream
from whodex.store.rows import EntityRow


class InMemoryLedgerStore:
    def __init__(self) -> None:
        self._obs: list[Observation] = []
        self._int: list[Interaction] = []
        self._act: list[UserAction] = []

    def append_observations(self, observations: Sequence[Observation]) -> None:
        self._obs.extend(observations)

    def append_interactions(self, interactions: Sequence[Interaction]) -> None:
        self._int.extend(interactions)

    def append_user_actions(self, actions: Sequence[UserAction]) -> None:
        self._act.extend(actions)

    def read_events(self) -> EventStream:
        return EventStream(
            observations=list(self._obs),
            interactions=list(self._int),
            user_actions=list(self._act),
        )


class InMemoryProjectionStore:
    def __init__(self) -> None:
        self._states: EntityGraphState = {}

    def save(self, states: EntityGraphState) -> None:
        self._states = dict(states)

    def load(self) -> EntityGraphState:
        return dict(self._states)


class InMemoryEntityStore:
    """In-memory EntityStore backed by plain dicts."""

    def __init__(self, id_factory: IdFactory) -> None:
        self._id_factory = id_factory
        # entity_id -> EntityRow
        self._entities: dict[str, EntityRow] = {}
        # (kind, normalised_value) -> entity_id
        self._index: dict[tuple[str, str], str] = {}

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
        self._entities[eid] = EntityRow(
            id=eid,
            kind=kind.value,
            subtype=subtype,
            created_at=created_at,
            vault_path=vault_path,
            vault_uid=vault_uid,
        )
        return eid

    def add_identifiers(self, entity_id: str, pairs: Sequence[tuple[str, str]]) -> None:
        for kind, value in pairs:
            normalised = normalize_identifier(kind, value)
            self._index[(kind, normalised)] = entity_id

    def find_by_identifiers(self, pairs: Sequence[tuple[str, str]]) -> str | None:
        for kind, value in pairs:
            normalised = normalize_identifier(kind, value)
            match = self._index.get((kind, normalised))
            if match is not None:
                return match
        return None

    def kinds(self) -> dict[str, EntityKind]:
        return {eid: EntityKind(row.kind) for eid, row in self._entities.items()}

    def get(self, entity_id: str) -> EntityRow | None:
        return self._entities.get(entity_id)


class InMemoryEdgeStore:
    """In-memory EdgeStore backed by a plain list."""

    def __init__(self) -> None:
        # Keyed by (src_entity_id, dst_entity_id, type) for O(1) dedup
        self._edges: dict[tuple[str, str, str], Edge] = {}

    def replace_edges(self, edges: Sequence[Edge]) -> None:
        self._edges = {(e.src_entity_id, e.dst_entity_id, e.type.value): e for e in edges}

    def outgoing(self, entity_id: str, type: EdgeType | None = None) -> list[Edge]:
        return [
            e
            for e in self._edges.values()
            if e.src_entity_id == entity_id and (type is None or e.type == type)
        ]

    def incoming(self, entity_id: str, type: EdgeType | None = None) -> list[Edge]:
        return [
            e
            for e in self._edges.values()
            if e.dst_entity_id == entity_id and (type is None or e.type == type)
        ]

    def all_edges(self) -> list[Edge]:
        return list(self._edges.values())
