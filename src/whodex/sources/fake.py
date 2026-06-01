from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from whodex.domain.enums import Capability
from whodex.domain.events import ObservationDraft, RawRecord
from whodex.sources.base import FieldMap, FieldSpec, apply_map

_MAP = [
    FieldMap("display_name", "name.full"),
    FieldMap("title", "job.title"),
    FieldMap("email", "email", transform=str.lower),
]


class FakeSource:
    id: str = "fake"
    capabilities: Capability = Capability.PULL
    identity_keys: tuple[str, ...] = ("email", "name.full")
    provides: tuple[FieldSpec, ...] = (FieldSpec(canonical="name.full"), FieldSpec(canonical="job.title"))

    def __init__(self, records: list[RawRecord]) -> None:
        self._records = records

    def fetch(self, since: datetime | None) -> Iterable[RawRecord]:
        return list(self._records)

    def normalize(self, record: RawRecord) -> list[ObservationDraft]:
        return apply_map(record, _MAP)
