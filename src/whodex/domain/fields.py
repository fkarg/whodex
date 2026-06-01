from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FieldKind(StrEnum):
    SCALAR = "scalar"  # single string/number/date
    MULTI = "multi"  # list of scalars (emails, phones, tags)
    REF = "ref"  # single EntityRef (person.lives)
    MULTI_REF = "multi_ref"  # list of EntityRef (person.organisations)


@dataclass(frozen=True)
class FieldDef:
    name: str
    kind: FieldKind
    volatile: bool = False  # feeds Significance.notable in change detection (§6.4)


def _f(name: str, kind: FieldKind, volatile: bool = False) -> tuple[str, FieldDef]:
    return name, FieldDef(name, kind, volatile)


FIELDS: dict[str, FieldDef] = dict(
    [
        # shared person atoms (flat paths)
        _f("name.full", FieldKind.SCALAR),
        _f("email", FieldKind.MULTI),
        _f("phone", FieldKind.MULTI),
        _f("linkedin.url", FieldKind.SCALAR),
        _f("job.title", FieldKind.SCALAR, volatile=True),
        _f("job.org", FieldKind.SCALAR, volatile=True),
        _f("birthday", FieldKind.SCALAR),
        _f("tags", FieldKind.MULTI),
        # person-specific / graph fields (kind.field paths)
        _f("person.organisations", FieldKind.MULTI_REF, volatile=True),
        _f("person.lives", FieldKind.REF, volatile=True),
        _f("person.importance", FieldKind.SCALAR),
        _f("person.cadence_days", FieldKind.SCALAR),
        _f("contact.next_at", FieldKind.SCALAR),
        _f("contact.last_at", FieldKind.SCALAR),
        # org fields
        _f("org.location", FieldKind.MULTI_REF),
        _f("org.parent", FieldKind.REF),
        _f("org.strategic_tier", FieldKind.SCALAR),
        _f("org.industry", FieldKind.MULTI),
        # event fields
        _f("event.datetime", FieldKind.SCALAR),
        _f("event.location", FieldKind.REF),
        _f("event.organizer", FieldKind.REF),
        _f("event.participants", FieldKind.MULTI_REF),
    ]
)


def is_valid_field(name: str) -> bool:
    return name in FIELDS


def field_def(name: str) -> FieldDef:
    return FIELDS[name]
