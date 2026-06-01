from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from whodex.domain.enums import EdgeType, EntityKind
from whodex.domain.events import Interaction, Observation, UserAction
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


class LedgerStore(Protocol):
    def append_observations(self, observations: Sequence[Observation]) -> None: ...
    def append_interactions(self, interactions: Sequence[Interaction]) -> None: ...
    def append_user_actions(self, actions: Sequence[UserAction]) -> None: ...
    def read_events(self) -> EventStream: ...


class ProjectionStore(Protocol):
    def save(self, states: EntityGraphState) -> None: ...
    def load(self) -> EntityGraphState: ...


class EntityStore(Protocol):
    def create_entity(
        self,
        kind: EntityKind,
        *,
        created_at: datetime,
        subtype: str | None = None,
        vault_path: str | None = None,
        vault_uid: str | None = None,
    ) -> str: ...

    def add_identifiers(self, entity_id: str, pairs: Sequence[tuple[str, str]]) -> None: ...

    def find_by_identifiers(self, pairs: Sequence[tuple[str, str]]) -> str | None: ...

    def kinds(self) -> dict[str, EntityKind]: ...

    def get(self, entity_id: str) -> EntityRow | None: ...


class EdgeStore(Protocol):
    def replace_edges(self, edges: Sequence[Edge]) -> None: ...

    def outgoing(self, entity_id: str, type: EdgeType | None = None) -> list[Edge]: ...

    def incoming(self, entity_id: str, type: EdgeType | None = None) -> list[Edge]: ...

    def all_edges(self) -> list[Edge]: ...


class DerivedStore(Protocol):
    """Full-snapshot store for derived rows (Changes, Conflicts, Repairs, Reminders).

    Each ``replace_*`` call is a complete snapshot: it deletes everything then
    inserts the new set, but preserves user-state overlay (seen/notified/status)
    for rows whose fingerprint matches an entry in *acked_fingerprints*.
    """

    def replace_changes(
        self,
        changes: Sequence[Change],
        *,
        acked_fingerprints: set[str] | None = None,
    ) -> None: ...

    def replace_conflicts(
        self,
        conflicts: Sequence[ConflictSuggestion],
        *,
        dismissed_fingerprints: set[str] | None = None,
    ) -> None: ...

    def replace_repairs(
        self,
        repairs: Sequence[GraphRepairSuggestion],
        *,
        dismissed_fingerprints: set[str] | None = None,
    ) -> None: ...

    def replace_reminders(self, reminders: Sequence[Reminder]) -> None: ...

    def changes(self) -> list[Change]: ...

    def conflicts(self) -> list[ConflictSuggestion]: ...

    def repairs(self) -> list[GraphRepairSuggestion]: ...

    def reminders(self) -> list[Reminder]: ...
