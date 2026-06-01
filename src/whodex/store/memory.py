from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from whodex.domain.enums import EntityKind
from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.identity import normalize_identifier
from whodex.domain.ids import IdFactory
from whodex.domain.state import EntityGraphState, EventStream
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
