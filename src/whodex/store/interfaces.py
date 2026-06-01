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
    VaultFileState,
)
from whodex.store.rows import EntityRow, TokenRow


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


class VaultStateStore(Protocol):
    """Upsert-by-path store for per-file vault tracking state."""

    def get(self, path: str) -> VaultFileState | None: ...

    def put(self, state: VaultFileState) -> None: ...

    def all(self) -> list[VaultFileState]: ...


class TokenStore(Protocol):
    """Store for revocable API bearer tokens.

    Plaintext is NEVER persisted; only the SHA-256 hash is stored.
    The caller is responsible for generating and displaying the plaintext once.
    """

    def issue(self, label: str, *, token: str, created_at: datetime) -> str:
        """Hash *token* and store a new row with *label*.  Returns the new token id."""
        ...

    def validate(self, token: str) -> bool:
        """Return True iff hash_token(*token*) matches a non-revoked row."""
        ...

    def revoke(self, token_id: str) -> None:
        """Mark the row identified by *token_id* as revoked."""
        ...

    def list_tokens(self) -> list[TokenRow]:
        """Return all token rows (id, label, created_at, revoked; hash included)."""
        ...


class SyncTokenStore(Protocol):
    """Tiny KV store for API sync tokens, keyed by source_id."""

    def get(self, source_id: str) -> str | None:
        """Return the stored token for *source_id*, or None if absent."""
        ...

    def set(self, source_id: str, token: str) -> None:
        """Persist *token* for *source_id*, overwriting any previous value."""
        ...

    def clear(self, source_id: str) -> None:
        """Remove the token for *source_id* (no-op if absent)."""
        ...


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
