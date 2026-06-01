from __future__ import annotations

from dataclasses import dataclass, field

from whodex.domain.canonical import value_hash
from whodex.domain.clock import Clock
from whodex.domain.enums import EntityKind, UserActionType
from whodex.domain.events import Interaction, Observation, ObservationDraft, RawRecord, UserAction
from whodex.domain.fields import is_valid_field
from whodex.domain.ids import IdFactory
from whodex.sources.base import Source
from whodex.store.interfaces import EntityStore, LedgerStore

# strong identity keys, in resolution priority order
# vault_uid and vault_path are vault-native stable identifiers;
# vault_path is always set by ObsidianSource and must participate in
# deduplication so that StoreIdentityResolver is idempotent across runs.
_STRONG_KEYS = ("vault_uid", "vault_path", "linkedin_url", "google_resource", "email", "phone")


def _strong_pairs(identity: dict[str, str]) -> list[tuple[str, str]]:
    """Return (key, value) pairs for recognised strong keys, in priority order."""
    return [(k, identity[k]) for k in _STRONG_KEYS if k in identity]


class IdentityResolver:
    """Phase-0 resolver: map a strong identity key to a stable entity id; create if new."""

    def __init__(self, ids: IdFactory) -> None:
        self._ids = ids
        self._by_key: dict[str, str] = {}
        self.kinds: dict[str, EntityKind] = {}

    def primary_ref(self, identity: dict[str, str]) -> str:
        for k in _STRONG_KEYS:
            if k in identity:
                return f"{k}:{identity[k].lower()}"
        return f"unknown:{sorted(identity.items())}"

    def resolve(self, identity: dict[str, str], *, kind: EntityKind = EntityKind.person) -> str:
        ref = self.primary_ref(identity)
        if ref not in self._by_key:
            eid = self._ids.new()
            self._by_key[ref] = eid
            self.kinds[eid] = kind
        return self._by_key[ref]


class StoreIdentityResolver:
    """Durable identity resolver backed by an EntityStore and a LedgerStore.

    Invariant I2: the same identity keys resolve to the same entity_id across
    independent resolver instances over the same durable EntityStore (i.e. across
    separate process runs).
    """

    def __init__(
        self,
        entities: EntityStore,
        ledger: LedgerStore,
        *,
        ids: IdFactory,
        clock: Clock,
    ) -> None:
        self._entities = entities
        self._ledger = ledger
        self._ids = ids
        self._clock = clock

    def primary_ref(self, identity: dict[str, str]) -> str:
        for k in _STRONG_KEYS:
            if k in identity:
                return f"{k}:{identity[k].lower()}"
        return f"unknown:{sorted(identity.items())}"

    def resolve(self, identity: dict[str, str], *, kind: EntityKind = EntityKind.person) -> str:
        pairs = _strong_pairs(identity)

        # Try to find an existing entity by any of the strong identifier pairs.
        eid = self._entities.find_by_identifiers(pairs)

        if eid is not None:
            # Entity already exists — add any new pairs so future lookups by other
            # keys also resolve to this entity.
            if pairs:
                self._entities.add_identifiers(eid, pairs)
            return eid

        # Entity not found — create a new one.
        now = self._clock.now()
        eid = self._entities.create_entity(kind, created_at=now)
        if pairs:
            self._entities.add_identifiers(eid, pairs)

        # Record the entity birth in the durable ledger.
        action = UserAction(
            id=self._ids.new(),
            action_type=UserActionType.entity_create,
            target_type="entity",
            target_id=eid,
            entity_id=eid,
            actor="system",
            created_at=now,
            payload={"kind": kind.value},
        )
        self._ledger.append_user_actions([action])

        return eid

    @property
    def kinds(self) -> dict[str, EntityKind]:
        """Delegate to the entity store — compatible with the engine's hub.identity.kinds access."""
        return self._entities.kinds()


@dataclass
class IngestResult:
    entity_id: str
    observations: list[Observation] = field(default_factory=list)
    interactions: list[Interaction] = field(default_factory=list)


class IngestionHub:
    def __init__(
        self,
        *,
        ids: IdFactory,
        clock: Clock,
        identity: IdentityResolver | StoreIdentityResolver,
    ) -> None:
        self._ids = ids
        self._clock = clock
        self.identity = identity

    def _finalize(
        self,
        draft: ObservationDraft,
        *,
        record: RawRecord,
        entity_id: str,
        source_kind: str,
        source_run_id: str,
        external_ref: str,
    ) -> Observation:
        if not is_valid_field(draft.field):
            raise ValueError(f"unknown field: {draft.field}")
        observed_at = draft.observed_at or record.observed_at
        return Observation(
            id=self._ids.new(),
            source_run_id=source_run_id,
            source_kind=source_kind,
            entity_id=entity_id,
            external_ref=external_ref,
            external_ref_kind=next(iter(record.identity), "unknown"),
            field=draft.field,
            op=draft.op,
            value=draft.value,
            value_hash=value_hash(draft.field, draft.op, draft.value),
            observed_at=observed_at,
            ingested_at=self._clock.now(),
            confidence=draft.confidence,
        )

    def ingest(self, source: Source, record: RawRecord, *, source_run_id: str) -> IngestResult:
        # Resolve kind: sources may embed a `_kind` string in the payload (e.g. ObsidianSource).
        kind_raw = record.payload.get("_kind")
        try:
            kind = EntityKind(kind_raw) if kind_raw else EntityKind.person
        except ValueError:
            kind = EntityKind.person
        entity_id = self.identity.resolve(record.identity, kind=kind)
        external_ref = self.identity.primary_ref(record.identity)
        obs = [
            self._finalize(
                d,
                record=record,
                entity_id=entity_id,
                source_kind=source.id,
                source_run_id=source_run_id,
                external_ref=external_ref,
            )
            for d in source.normalize(record)
        ]

        # Interactions: finalize any InteractionDrafts from sources that expose them.
        interactions: list[Interaction] = []
        interactions_fn = getattr(source, "interactions", None)
        if interactions_fn is not None:
            for draft in interactions_fn(record):
                interactions.append(
                    Interaction(
                        id=self._ids.new(),
                        kind=draft.kind,
                        occurred_at=draft.occurred_at,
                        participant_ids=(entity_id,),
                        summary=draft.summary,
                        source_run_id=source_run_id,
                        created_at=self._clock.now(),
                    )
                )

        return IngestResult(entity_id=entity_id, observations=obs, interactions=interactions)
