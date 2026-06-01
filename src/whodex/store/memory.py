from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from whodex.domain.enums import EdgeType, EntityKind, SuggestionStatus
from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.identity import normalize_identifier
from whodex.domain.ids import IdFactory
from whodex.domain.state import (
    Change,
    ConflictSuggestion,
    Edge,
    EntityGraphState,
    EventStream,
    GraphRepairSuggestion,
    Reminder,
)
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


class InMemoryDerivedStore:
    """In-memory DerivedStore. Full-snapshot semantics with user-state overlay."""

    def __init__(self) -> None:
        self._changes: dict[str, Change] = {}  # fingerprint -> Change
        self._conflicts: dict[str, ConflictSuggestion] = {}  # fingerprint -> ConflictSuggestion
        self._repairs: dict[str, GraphRepairSuggestion] = {}  # fingerprint -> GraphRepairSuggestion
        self._reminders: dict[str, Reminder] = {}  # fingerprint -> Reminder

    def replace_changes(
        self,
        changes: Sequence[Change],
        *,
        acked_fingerprints: set[str] | None = None,
    ) -> None:
        acked = acked_fingerprints or set()
        new: dict[str, Change] = {}
        for c in changes:
            fp = c.fingerprint
            prev = self._changes.get(fp)
            if prev is not None and (prev.seen or prev.notified):
                # Preserve existing user state
                c = c.model_copy(update={"seen": prev.seen, "notified": prev.notified})
            elif fp in acked:
                c = c.model_copy(update={"seen": True})
            new[fp] = c
        self._changes = new

    def replace_conflicts(
        self,
        conflicts: Sequence[ConflictSuggestion],
        *,
        dismissed_fingerprints: set[str] | None = None,
    ) -> None:
        dismissed = dismissed_fingerprints or set()
        new: dict[str, ConflictSuggestion] = {}
        for c in conflicts:
            fp = c.fingerprint
            prev = self._conflicts.get(fp)
            if prev is not None and prev.status != SuggestionStatus.open:
                c = c.model_copy(update={"status": prev.status})
            elif fp in dismissed:
                c = c.model_copy(update={"status": SuggestionStatus.dismissed})
            new[fp] = c
        self._conflicts = new

    def replace_repairs(
        self,
        repairs: Sequence[GraphRepairSuggestion],
        *,
        dismissed_fingerprints: set[str] | None = None,
    ) -> None:
        dismissed = dismissed_fingerprints or set()
        new: dict[str, GraphRepairSuggestion] = {}
        for r in repairs:
            fp = r.fingerprint
            prev = self._repairs.get(fp)
            if prev is not None and prev.status != SuggestionStatus.open:
                r = r.model_copy(update={"status": prev.status})
            elif fp in dismissed:
                r = r.model_copy(update={"status": SuggestionStatus.dismissed})
            new[fp] = r
        self._repairs = new

    def replace_reminders(self, reminders: Sequence[Reminder]) -> None:
        self._reminders = {r.fingerprint: r for r in reminders}

    def changes(self) -> list[Change]:
        return list(self._changes.values())

    def conflicts(self) -> list[ConflictSuggestion]:
        return list(self._conflicts.values())

    def repairs(self) -> list[GraphRepairSuggestion]:
        return list(self._repairs.values())

    def reminders(self) -> list[Reminder]:
        return list(self._reminders.values())
