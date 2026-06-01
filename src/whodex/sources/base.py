from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from whodex.domain.enums import Capability
from whodex.domain.events import ObservationDraft, RawRecord

__all__ = [
    "Capability",
    "FieldSpec",
    "Source",
    "PullSource",
    "FieldMap",
    "apply_map",
]


class FieldSpec(BaseModel):
    canonical: str
    freshness_ttl_days: int | None = None


@runtime_checkable
class Source(Protocol):
    id: str
    capabilities: Capability
    identity_keys: tuple[str, ...]
    provides: tuple[FieldSpec, ...]

    def normalize(self, record: RawRecord) -> list[ObservationDraft]: ...


@runtime_checkable
class PullSource(Source, Protocol):
    def fetch(self, since: datetime | None) -> Iterable[RawRecord]: ...


@dataclass(frozen=True)
class FieldMap:
    source_path: str  # dotted path into payload, e.g. "organizations.0.title"
    canonical: str  # canonical field name
    transform: Callable[[Any], Any] | None = None
    skip_if_empty: bool = True


def _dig(payload: dict[str, Any], path: str) -> Any:
    cur: Any = payload
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def apply_map(record: RawRecord, fields: list[FieldMap]) -> list[ObservationDraft]:
    drafts: list[ObservationDraft] = []
    for fm in fields:
        value = _dig(record.payload, fm.source_path)
        if value is None and fm.skip_if_empty:
            continue
        if fm.transform is not None and value is not None:
            value = fm.transform(value)
        drafts.append(
            ObservationDraft(field=fm.canonical, value=value, observed_at=record.observed_at)
        )
    return drafts
