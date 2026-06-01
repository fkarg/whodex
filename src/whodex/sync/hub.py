from __future__ import annotations

from dataclasses import dataclass, field

from whodex.domain.canonical import value_hash
from whodex.domain.clock import Clock
from whodex.domain.enums import EntityKind
from whodex.domain.events import Observation, ObservationDraft, RawRecord
from whodex.domain.fields import is_valid_field
from whodex.domain.ids import IdFactory
from whodex.sources.base import Source

# strong identity keys, in resolution priority order
_STRONG_KEYS = ("vault_uid", "linkedin_url", "google_resource", "email", "phone")


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


@dataclass
class IngestResult:
    entity_id: str
    observations: list[Observation] = field(default_factory=list)


class IngestionHub:
    def __init__(self, *, ids: IdFactory, clock: Clock, identity: IdentityResolver) -> None:
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
        entity_id = self.identity.resolve(record.identity)
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
        return IngestResult(entity_id=entity_id, observations=obs)
