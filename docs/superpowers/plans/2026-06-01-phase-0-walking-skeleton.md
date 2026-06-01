# whodex Phase 0 — Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an end-to-end vertical slice — a `FakeSource` flows through the ingestion hub into an append-only ledger, a pure projector folds the ledger into entity state with deterministic precedence + change/conflict detection, and `whodex sync` materializes that state identically in an in-memory store and SQLite — all behind CI gates (`ruff`, `mypy --strict`, `import-linter`, `pytest`).

**Architecture:** Pure functional core (`domain` + `projection` + `engine`), impure shell at the edges (`store`, `sources`, `sync`, `cli`). The append-only event ledger is the only write target; everything else is a deterministic fold over it. Time and IDs are injected (no ambient `datetime.now()`), so projection is reproducible and trivially testable.

**Tech Stack:** Python 3.12, `uv` + `hatchling` (src-layout), `pydantic` v2, `SQLModel`/SQLAlchemy (store only), `Typer` (CLI), `pytest` + `hypothesis` + `syrupy`, `ruff`, `mypy --strict`, `import-linter`, `python-ulid`.

---

## Scope & deviations from DESIGN §13

This plan implements **only Phase 0**. It deliberately narrows two items from the DESIGN §13 Phase-0 bullet list, because they cannot be exercised without a real vault/connector and belong to Phase 1:

- **Edge projection + graph-repair *rules* are deferred to Phase 1.** Phase 0 ships the `Edge` and `GraphRepairSuggestion` domain models and the (empty) `graph_repairs` slot on `ProjectionResult` — the *seam* exists and is type-checked — but no repair rules run (a `FakeSource` produces nothing to repair).
- **JSONL ledger mirror is deferred to Phase 1.** Phase 0 proves SQLite ≡ in-memory parity; the disaster-recovery JSONL mirror lands with the Obsidian connector.

Everything else in the DESIGN §13 Phase-0 list is in scope: scaffolding, the domain models, the pure projector (precedence §6.1–6.3, change detection §6.4, conflict suggestions §6.5), in-memory + SQLite stores behind one interface, the `Source` protocol + `FakeSource`, `sync.run_sync`, the `whodex sync` CLI, and the `obs()/interaction()/action()` test DSL.

**Locked design clarifications (see plan intro):** `domain` is pure pydantic; SQLModel rows live in `store/rows.py`; `RawRecord`/`ObservationDraft` live in `domain` (shared transport); source trust is looked up at projection time from a `TrustTable` (config data, never baked into the ledger), so the pure `Observation` carries a denormalized immutable `source_kind` string.

**Conventions for every task:** TDD (red → green → commit). Run the full gate before each commit:
`uv run ruff format . && uv run ruff check . && uv run mypy --strict src && uv run lint-imports && uv run pytest -q`.
Commits are conventional and scoped. **Do not add a `Co-Authored-By` / AI co-author trailer** (user preference). Work on a branch off `main`.

---

## File structure (locked before tasks)

```
whodex/
├── pyproject.toml                  # uv/hatchling, deps, ruff, mypy, pytest config
├── .importlinter                   # dependency contracts
├── .github/workflows/ci.yml        # CI gate
├── src/whodex/
│   ├── __init__.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── clock.py                # Clock protocol, SystemClock, FixedClock
│   │   ├── ids.py                  # IdFactory protocol, UlidIdFactory, SequentialIdFactory
│   │   ├── enums.py                # ObsOp, EntityKind, EdgeType, … (all enums)
│   │   ├── fields.py               # closed canonical field registry (~20) + helpers
│   │   ├── refs.py                 # EntityRef
│   │   ├── canonical.py            # canonicalize() + value_hash()
│   │   ├── trust.py                # DEFAULT_TRUST table (§6.2)
│   │   ├── events.py               # RawRecord, ObservationDraft, Observation, Interaction, UserAction
│   │   └── state.py                # FieldValue, EntityState, ContactProfileState, Change,
│   │                               #   ConflictSuggestion, GraphRepairSuggestion, Edge,
│   │                               #   EventStream, EntityGraphState, ProjectionResult
│   ├── projection/
│   │   ├── __init__.py
│   │   ├── conflict.py             # resolve_field() precedence comparator (§6.1–6.3)
│   │   └── project.py              # project() pure fold (+ change §6.4, conflict §6.5)
│   ├── store/
│   │   ├── __init__.py
│   │   ├── interfaces.py           # LedgerStore, ProjectionStore protocols
│   │   ├── memory.py               # InMemoryLedgerStore, InMemoryProjectionStore
│   │   ├── rows.py                 # SQLModel table classes
│   │   ├── mappers.py              # domain <-> row mappers
│   │   └── sqlite.py               # SqliteLedgerStore, SqliteProjectionStore
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py                 # Capability, FieldSpec, Source/PullSource, FieldMap, apply_map
│   │   └── fake.py                 # FakeSource
│   ├── sync/
│   │   ├── __init__.py
│   │   ├── hub.py                  # ObservationFactory, IdentityResolver, IngestionHub, IngestResult
│   │   └── engine.py               # run_sync(), SyncReport
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py             # Settings + build_app() composition root
│   └── cli/
│       ├── __init__.py
│       └── main.py                 # Typer app: `whodex sync`
└── tests/
    ├── conftest.py                 # obs()/interaction()/action()/raw() builders + fixtures
    ├── domain/  projection/  store/  sources/  sync/  cli/   # mirror src tree
    └── test_e2e_phase0.py          # acceptance: §13 "done when"
```

Dependency directions (enforced in Task 1): `domain` → nothing; `projection`/`engine` → `domain`; `store` → `domain` (+SQLModel); `sources` → `domain`; `sync` → all; `cli` → `sync`/`config`; `config` → everything.

---

### Task 1: Repo scaffolding + tooling + CI gate

**Files:**
- Create: `pyproject.toml`, `.importlinter`, `.github/workflows/ci.yml`, `src/whodex/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "whodex"
version = "0.0.0"
description = "Local-first people CRM over an Obsidian vault"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "sqlmodel>=0.0.21",
    "typer>=0.12",
    "python-ulid>=2.7",
]

[project.scripts]
whodex = "whodex.cli.main:app"

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-cov>=5.0",
    "hypothesis>=6.100",
    "syrupy>=4.6",
    "ruff>=0.5",
    "mypy>=1.10",
    "import-linter>=2.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/whodex"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
mypy_path = "src"
explicit_package_bases = true

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]
markers = [
    "unit: pure-function unit tests",
    "integration: cross-component tests",
    "e2e: end-to-end golden paths",
]
```

- [ ] **Step 2: Create `.importlinter`**

```ini
[importlinter]
root_package = whodex

[importlinter:contract:layers]
name = whodex layered architecture
type = layers
layers =
    whodex.cli
    whodex.config
    whodex.sync
    whodex.ingestion | whodex.notifiers | whodex.tui
    whodex.engine | whodex.projection
    whodex.store | whodex.sources | whodex.vault
    whodex.domain
ignore_imports =
    whodex.config -> *

[importlinter:contract:domain-purity]
name = domain depends on nothing internal
type = forbidden
source_modules = whodex.domain
forbidden_modules =
    whodex.store
    whodex.sources
    whodex.projection
    whodex.engine
    whodex.sync
    whodex.cli
    whodex.config
```

- [ ] **Step 3: Create package markers and a smoke test**

Create `src/whodex/__init__.py`:
```python
"""whodex — local-first people CRM."""

__version__ = "0.0.0"
```

Create `tests/__init__.py` (empty file).

Create `tests/test_smoke.py`:
```python
import whodex


def test_package_imports():
    assert whodex.__version__ == "0.0.0"
```

- [ ] **Step 4: Create `.github/workflows/ci.yml`**

```yaml
name: ci
on: [push, pull_request]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv python install 3.12
      - run: uv sync
      - run: uv run ruff format --check .
      - run: uv run ruff check .
      - run: uv run mypy --strict src
      - run: uv run lint-imports
      - run: uv run pytest -q --cov=whodex
```

- [ ] **Step 5: Install and run the full gate**

Run: `uv sync && uv run ruff format . && uv run ruff check . && uv run mypy --strict src && uv run lint-imports && uv run pytest -q`
Expected: all pass; pytest reports `1 passed`. `lint-imports` reports both contracts kept.

- [ ] **Step 6: Commit**

```bash
git checkout -b phase-0-walking-skeleton
git add -A
git commit -m "chore: scaffold whodex package, tooling, and CI gate"
```

---

### Task 2: `domain.clock` and `domain.ids` (the determinism seams)

**Files:**
- Create: `src/whodex/domain/__init__.py` (empty), `src/whodex/domain/clock.py`, `src/whodex/domain/ids.py`
- Test: `tests/domain/__init__.py` (empty), `tests/domain/test_clock.py`, `tests/domain/test_ids.py`

- [ ] **Step 1: Write failing tests for the clock**

Create `tests/domain/test_clock.py`:
```python
from datetime import UTC, datetime, timedelta

from whodex.domain.clock import FixedClock, SystemClock


def test_fixed_clock_returns_its_time():
    t = datetime(2026, 6, 1, tzinfo=UTC)
    assert FixedClock(t).now() == t


def test_fixed_clock_advance():
    t = datetime(2026, 6, 1, tzinfo=UTC)
    clock = FixedClock(t)
    clock.advance(timedelta(days=2))
    assert clock.now() == t + timedelta(days=2)


def test_system_clock_is_tz_aware_utc():
    assert SystemClock().now().tzinfo == UTC
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/domain/test_clock.py -q`
Expected: FAIL with `ModuleNotFoundError: whodex.domain.clock`.

- [ ] **Step 3: Implement `clock.py`**

Create `src/whodex/domain/__init__.py` (empty), then `src/whodex/domain/clock.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta
```

- [ ] **Step 4: Write failing tests for ids**

Create `tests/domain/test_ids.py`:
```python
from whodex.domain.ids import SequentialIdFactory, UlidIdFactory


def test_sequential_ids_are_stable_and_ordered():
    f = SequentialIdFactory(prefix="OBS")
    assert f.new() == "OBS-00000001"
    assert f.new() == "OBS-00000002"


def test_ulid_ids_are_unique_and_sortable():
    f = UlidIdFactory()
    a, b = f.new(), f.new()
    assert a != b
    assert len(a) == 26
```

- [ ] **Step 5: Run to verify failure**

Run: `uv run pytest tests/domain/test_ids.py -q`
Expected: FAIL with `ModuleNotFoundError: whodex.domain.ids`.

- [ ] **Step 6: Implement `ids.py`**

Create `src/whodex/domain/ids.py`:
```python
from __future__ import annotations

from typing import Protocol

from ulid import ULID


class IdFactory(Protocol):
    def new(self) -> str: ...


class UlidIdFactory:
    def new(self) -> str:
        return str(ULID())


class SequentialIdFactory:
    """Deterministic IDs for tests — stable snapshots."""

    def __init__(self, prefix: str = "ID") -> None:
        self._prefix = prefix
        self._n = 0

    def new(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n:08d}"
```

- [ ] **Step 7: Run the gate and commit**

Run: `uv run mypy --strict src && uv run pytest tests/domain -q`
Expected: PASS (5 tests).
```bash
git add src/whodex/domain tests/domain
git commit -m "feat(domain): add Clock and IdFactory seams"
```

---

### Task 3: `domain.enums` and `domain.fields` (the vocabulary)

**Files:**
- Create: `src/whodex/domain/enums.py`, `src/whodex/domain/fields.py`
- Test: `tests/domain/test_fields.py`

- [ ] **Step 1: Implement `enums.py` (no test — pure declarations exercised later)**

Create `src/whodex/domain/enums.py`:
```python
from __future__ import annotations

from enum import Enum, Flag, auto


class ObsOp(str, Enum):
    set = "set"
    add = "add"
    remove = "remove"
    assert_absent = "assert_absent"


class EntityKind(str, Enum):
    person = "person"
    organisation = "organisation"
    location = "location"
    event = "event"


class IdKind(str, Enum):
    email = "email"
    phone = "phone"
    linkedin_url = "linkedin_url"
    google_resource = "google_resource"
    vault_uid = "vault_uid"
    vault_path = "vault_path"
    canonical_name = "canonical_name"
    wikilink = "wikilink"


class EdgeType(str, Enum):
    knows = "knows"
    member_of = "member_of"
    lives_in = "lives_in"
    located_in = "located_in"
    part_of = "part_of"
    hosted_at = "hosted_at"
    organized_by = "organized_by"
    attended = "attended"


class Significance(str, Enum):
    trivial = "trivial"
    minor = "minor"
    notable = "notable"


class InteractionKind(str, Enum):
    met = "met"
    call = "call"
    message = "message"
    email = "email"
    note = "note"
    introduced = "introduced"


class UserActionType(str, Enum):
    entity_create = "entity_create"
    pin = "pin"
    unpin = "unpin"
    snooze = "snooze"
    dismiss = "dismiss"
    ack_change = "ack_change"
    merge = "merge"
    unmerge = "unmerge"
    archive = "archive"
    cadence_set = "cadence_set"


class Capability(Flag):
    PULL = auto()
    PUSH = auto()
    WRITEBACK = auto()
    WATCH = auto()
```

- [ ] **Step 2: Write failing tests for the field registry**

Create `tests/domain/test_fields.py`:
```python
import pytest

from whodex.domain.fields import FIELDS, FieldKind, field_def, is_valid_field


def test_known_fields_present():
    assert is_valid_field("job.title")
    assert is_valid_field("person.organisations")
    assert is_valid_field("email")


def test_unknown_field_is_invalid():
    assert not is_valid_field("totally.bogus")


def test_field_def_exposes_kind_and_volatility():
    d = field_def("person.organisations")
    assert d.kind == FieldKind.MULTI_REF
    assert field_def("job.title").volatile is True
    assert field_def("email").volatile is False


def test_field_def_raises_on_unknown():
    with pytest.raises(KeyError):
        field_def("nope")


def test_registry_has_about_twenty_fields():
    assert 18 <= len(FIELDS) <= 24
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/domain/test_fields.py -q`
Expected: FAIL with `ModuleNotFoundError: whodex.domain.fields`.

- [ ] **Step 4: Implement `fields.py`**

Create `src/whodex/domain/fields.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FieldKind(str, Enum):
    SCALAR = "scalar"        # single string/number/date
    MULTI = "multi"          # list of scalars (emails, phones, tags)
    REF = "ref"              # single EntityRef (person.lives)
    MULTI_REF = "multi_ref"  # list of EntityRef (person.organisations)


@dataclass(frozen=True)
class FieldDef:
    name: str
    kind: FieldKind
    volatile: bool = False   # feeds Significance.notable in change detection (§6.4)


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
```

- [ ] **Step 5: Run the gate and commit**

Run: `uv run mypy --strict src && uv run pytest tests/domain -q`
Expected: PASS.
```bash
git add src/whodex/domain/enums.py src/whodex/domain/fields.py tests/domain/test_fields.py
git commit -m "feat(domain): add enums and closed field registry"
```

---

### Task 4: `domain.refs`, `domain.canonical`, `domain.trust`

**Files:**
- Create: `src/whodex/domain/refs.py`, `src/whodex/domain/canonical.py`, `src/whodex/domain/trust.py`
- Test: `tests/domain/test_refs.py`, `tests/domain/test_canonical.py`

- [ ] **Step 1: Write failing tests for EntityRef parsing**

Create `tests/domain/test_refs.py`:
```python
from whodex.domain.refs import EntityRef


def test_parse_aliased_wikilink():
    r = EntityRef.parse("[[Organisations/Kolai|Kolai]]")
    assert r.target_path == "Organisations/Kolai"
    assert r.label == "Kolai"
    assert r.raw == "[[Organisations/Kolai|Kolai]]"
    assert r.resolution == "unresolved"


def test_parse_bare_wikilink():
    r = EntityRef.parse("[[Kolai]]")
    assert r.target_path == "Kolai"
    assert r.label == "Kolai"


def test_parse_scalar_placeholder():
    r = EntityRef.parse("Sydney")
    assert r.target_path is None
    assert r.label == "Sydney"
    assert r.raw == "Sydney"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/domain/test_refs.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `refs.py`**

Create `src/whodex/domain/refs.py`:
```python
from __future__ import annotations

import re

from pydantic import BaseModel

_WIKILINK = re.compile(r"^\[\[(?P<target>[^|\]]+?)(?:\|(?P<label>[^\]]+))?\]\]$")


class EntityRef(BaseModel):
    entity_id: str | None = None
    target_path: str | None = None
    label: str | None = None
    raw: str
    resolution: str = "unresolved"  # resolved|ambiguous|missing|placeholder|unresolved

    @classmethod
    def parse(cls, raw: str) -> EntityRef:
        raw = raw.strip()
        m = _WIKILINK.match(raw)
        if m:
            target = m.group("target").strip()
            label = (m.group("label") or target.split("/")[-1]).strip()
            return cls(target_path=target, label=label, raw=raw)
        return cls(target_path=None, label=raw, raw=raw)
```

- [ ] **Step 4: Write failing tests for canonicalization + hashing**

Create `tests/domain/test_canonical.py`:
```python
from whodex.domain.canonical import canonicalize, value_hash
from whodex.domain.enums import ObsOp


def test_canonicalize_strips_and_collapses_whitespace():
    assert canonicalize("job.title", "  Staff   Engineer ") == "Staff Engineer"


def test_canonicalize_lowercases_email():
    assert canonicalize("email", "Jane@Acme.COM") == "jane@acme.com"


def test_value_hash_is_stable_across_equivalent_values():
    a = value_hash("job.title", ObsOp.set, "Staff   Engineer")
    b = value_hash("job.title", ObsOp.set, "Staff Engineer")
    assert a == b


def test_value_hash_differs_on_field():
    a = value_hash("job.title", ObsOp.set, "X")
    b = value_hash("job.org", ObsOp.set, "X")
    assert a != b
```

- [ ] **Step 5: Run to verify failure**

Run: `uv run pytest tests/domain/test_canonical.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 6: Implement `canonical.py` and `trust.py`**

Create `src/whodex/domain/canonical.py`:
```python
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from whodex.domain.enums import ObsOp

_WS = re.compile(r"\s+")
_LOWER_FIELDS = {"email", "linkedin.url"}


def canonicalize(field: str, value: Any) -> Any:
    """Normalize a value so cosmetic differences are not treated as changes (§6.4)."""
    if isinstance(value, str):
        out = _WS.sub(" ", value).strip()
        if field in _LOWER_FIELDS:
            out = out.lower()
        return out
    if isinstance(value, list):
        return [canonicalize(field, v) for v in value]
    return value


def value_hash(field: str, op: ObsOp, value: Any) -> str:
    payload = json.dumps(
        {"field": field, "op": op.value, "value": canonicalize(field, value)},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```

Create `src/whodex/domain/trust.py`:
```python
from __future__ import annotations

# Default precedence ranks (DESIGN §6.2). Config may override; never baked into the ledger.
DEFAULT_TRUST: dict[str, int] = {
    "manual_cli": 100,
    "obsidian": 80,
    "google_contacts": 60,
    "linkedin_ext": 50,
    "linkedin_api": 40,
    "linkedin_rss": 30,
    "llm": 25,
    "webhook": 20,
    "fake": 10,  # Phase-0 test source
}
```

- [ ] **Step 7: Run the gate and commit**

Run: `uv run mypy --strict src && uv run pytest tests/domain -q`
Expected: PASS.
```bash
git add src/whodex/domain/refs.py src/whodex/domain/canonical.py src/whodex/domain/trust.py tests/domain/test_refs.py tests/domain/test_canonical.py
git commit -m "feat(domain): EntityRef parsing, value canonicalization, trust table"
```

---

### Task 5: `domain.events` (the three ledger streams + transport DTOs)

**Files:**
- Create: `src/whodex/domain/events.py`
- Test: `tests/domain/test_events.py`

- [ ] **Step 1: Write failing tests**

Create `tests/domain/test_events.py`:
```python
from datetime import UTC, datetime

from whodex.domain.enums import ObsOp
from whodex.domain.events import Observation, ObservationDraft, RawRecord


def test_observation_is_immutable():
    o = Observation(
        id="OBS-1", source_run_id="RUN-1", source_kind="fake", entity_id="E1",
        external_ref="ext", external_ref_kind="fake_id", field="job.title",
        op=ObsOp.set, value="Eng", value_hash="h",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    try:
        o.value = "Other"  # type: ignore[misc]
        raise AssertionError("expected immutability error")
    except Exception:
        pass


def test_observation_draft_defaults():
    d = ObservationDraft(field="email", value="a@b.com")
    assert d.op == ObsOp.set
    assert d.observed_at is None
    assert d.confidence == 1.0


def test_raw_record_roundtrips():
    r = RawRecord(
        source="fake", identity={"email": "a@b.com"}, payload={"x": 1},
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert r.source == "fake"
    assert r.identity["email"] == "a@b.com"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/domain/test_events.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `events.py`**

Create `src/whodex/domain/events.py`:
```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from whodex.domain.enums import InteractionKind, ObsOp, UserActionType

_FROZEN = ConfigDict(frozen=True)


class RawRecord(BaseModel):
    """Producer output BEFORE field-mapping; also the ingestion API wire shape."""

    source: str
    identity: dict[str, str]
    payload: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    capture_context: dict[str, Any] = Field(default_factory=dict)


class ObservationDraft(BaseModel):
    """Connector output. The hub turns drafts into persisted Observations."""

    field: str
    op: ObsOp = ObsOp.set
    value: Any = None
    observed_at: datetime | None = None
    confidence: float = 1.0


class Observation(BaseModel):
    model_config = _FROZEN

    id: str
    source_run_id: str
    source_kind: str  # immutable per run; trust looked up from this at projection time
    entity_id: str | None = None
    external_ref: str
    external_ref_kind: str
    field: str
    op: ObsOp = ObsOp.set
    value: Any = None
    value_hash: str
    observed_at: datetime
    ingested_at: datetime
    confidence: float = 1.0
    raw_ref: str | None = None


class Interaction(BaseModel):
    model_config = _FROZEN

    id: str
    kind: InteractionKind
    occurred_at: datetime
    participant_ids: tuple[str, ...] = ()
    summary: str | None = None
    source_run_id: str | None = None
    created_at: datetime


class UserAction(BaseModel):
    model_config = _FROZEN

    id: str
    action_type: UserActionType
    target_type: str
    target_id: str
    entity_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    actor: str = "user"
```

- [ ] **Step 4: Run the gate and commit**

Run: `uv run mypy --strict src && uv run pytest tests/domain -q`
Expected: PASS.
```bash
git add src/whodex/domain/events.py tests/domain/test_events.py
git commit -m "feat(domain): Observation/Interaction/UserAction streams + transport DTOs"
```

---

### Task 6: `domain.state` (projection structs + result)

**Files:**
- Create: `src/whodex/domain/state.py`
- Test: `tests/domain/test_state.py`

- [ ] **Step 1: Write failing tests**

Create `tests/domain/test_state.py`:
```python
from datetime import UTC, datetime

from whodex.domain.enums import EntityKind
from whodex.domain.state import EntityState, FieldValue, ProjectionResult


def test_entity_state_field_lookup():
    fv = FieldValue(
        field="job.title", value="Eng", source_kind="fake",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC), pinned=False,
    )
    s = EntityState(entity_id="E1", kind=EntityKind.person, display_name="Jane", fields={"job.title": fv})
    assert s.fields["job.title"].value == "Eng"


def test_empty_projection_result():
    r = ProjectionResult()
    assert r.states == {}
    assert r.changes == []
    assert r.conflict_suggestions == []
    assert r.graph_repairs == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/domain/test_state.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `state.py`**

Create `src/whodex/domain/state.py`:
```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from whodex.domain.enums import EdgeType, EntityKind, Significance
from whodex.domain.events import Interaction, Observation, UserAction


class FieldValue(BaseModel):
    field: str
    value: Any
    source_kind: str
    observed_at: datetime
    ingested_at: datetime
    pinned: bool = False


class EntityState(BaseModel):
    entity_id: str
    kind: EntityKind
    display_name: str | None = None
    fields: dict[str, FieldValue] = Field(default_factory=dict)


class ContactProfileState(BaseModel):
    entity_id: str
    job_title: str | None = None
    primary_email: str | None = None
    linkedin_url: str | None = None
    last_interaction_at: datetime | None = None


class Change(BaseModel):
    id: str
    entity_id: str
    field: str
    old_value: Any = None
    new_value: Any = None
    caused_by_observation: str
    detected_at: datetime
    significance: Significance = Significance.minor


class ConflictSuggestion(BaseModel):
    id: str
    entity_id: str
    field: str
    winning_observation_id: str
    disagreeing_observation_id: str
    reason: str
    fingerprint: str
    detected_at: datetime


class GraphRepairSuggestion(BaseModel):  # seam only in Phase 0
    id: str
    repair_type: str
    src_entity_id: str | None = None
    dst_entity_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str
    detected_at: datetime


class Edge(BaseModel):  # seam only in Phase 0
    id: str
    src_entity_id: str
    dst_entity_id: str
    type: EdgeType
    weight: float = 1.0
    observed_at: datetime | None = None


class EventStream(BaseModel):
    observations: list[Observation] = Field(default_factory=list)
    interactions: list[Interaction] = Field(default_factory=list)
    user_actions: list[UserAction] = Field(default_factory=list)


EntityGraphState = dict[str, EntityState]


class ProjectionResult(BaseModel):
    states: EntityGraphState = Field(default_factory=dict)
    changes: list[Change] = Field(default_factory=list)
    conflict_suggestions: list[ConflictSuggestion] = Field(default_factory=list)
    graph_repairs: list[GraphRepairSuggestion] = Field(default_factory=list)
```

- [ ] **Step 4: Run the gate and commit**

Run: `uv run mypy --strict src && uv run pytest tests/domain -q`
Expected: PASS.
```bash
git add src/whodex/domain/state.py tests/domain/test_state.py
git commit -m "feat(domain): projection state structs and ProjectionResult"
```

---

### Task 7: Test DSL (`obs()/interaction()/action()/raw()`)

**Files:**
- Create: `tests/conftest.py`, `tests/domain/__init__.py` already exists; create `tests/projection/__init__.py`
- Test: `tests/test_builders.py`

This is the highest-leverage testing investment (DESIGN §12): the ledger is the fixture format.

- [ ] **Step 1: Implement `tests/conftest.py`**

Create `tests/conftest.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from whodex.domain.canonical import value_hash
from whodex.domain.enums import InteractionKind, ObsOp, UserActionType
from whodex.domain.events import Interaction, Observation, RawRecord, UserAction

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _t(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


_counter = {"n": 0}


def _id(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:04d}"


def obs(
    *, entity: str, field: str, value: Any, source: str = "fake",
    op: ObsOp = ObsOp.set, observed: datetime = T0, ingested: datetime | None = None,
    confidence: float = 1.0, ext: str | None = None,
) -> Observation:
    return Observation(
        id=_id("OBS"), source_run_id="RUN-TEST", source_kind=source, entity_id=entity,
        external_ref=ext or entity, external_ref_kind=f"{source}_id", field=field, op=op,
        value=value, value_hash=value_hash(field, op, value), observed_at=observed,
        ingested_at=ingested or observed, confidence=confidence,
    )


def interaction(*, entities: tuple[str, ...], kind: InteractionKind = InteractionKind.met,
                occurred: datetime = T0) -> Interaction:
    return Interaction(id=_id("INT"), kind=kind, occurred_at=occurred,
                       participant_ids=entities, created_at=occurred)


def action(*, action_type: UserActionType, target_type: str, target_id: str,
           entity: str | None = None, payload: dict[str, Any] | None = None,
           created: datetime = T0) -> UserAction:
    return UserAction(id=_id("ACT"), action_type=action_type, target_type=target_type,
                      target_id=target_id, entity_id=entity, payload=payload or {}, created_at=created)


def raw(*, source: str = "fake", identity: dict[str, str], payload: dict[str, Any] | None = None,
        observed: datetime = T0) -> RawRecord:
    return RawRecord(source=source, identity=identity, payload=payload or {}, observed_at=observed)
```

- [ ] **Step 2: Write a test that exercises the builders**

Create `tests/test_builders.py`:
```python
from tests.conftest import _t, action, interaction, obs, raw
from whodex.domain.enums import UserActionType


def test_obs_builder_sets_hash_and_entity():
    o = obs(entity="E1", field="job.title", value="Eng")
    assert o.entity_id == "E1"
    assert o.value_hash


def test_builders_produce_unique_ids():
    a = obs(entity="E1", field="email", value="a@b.com")
    b = obs(entity="E1", field="email", value="c@d.com")
    assert a.id != b.id


def test_interaction_and_action_and_raw():
    assert interaction(entities=("E1",)).participant_ids == ("E1",)
    act = action(action_type=UserActionType.pin, target_type="field", target_id="E1:job.title")
    assert act.action_type == UserActionType.pin
    assert raw(identity={"email": "a@b.com"}, observed=_t(3)).source == "fake"
```

- [ ] **Step 3: Run to verify it passes (builders import real domain types)**

Run: `uv run pytest tests/test_builders.py -q`
Expected: PASS (3 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/test_builders.py tests/projection/__init__.py
git commit -m "test: add ledger-as-fixture builder DSL"
```

---

### Task 8: `projection.conflict` — the precedence comparator (§6.1–6.3)

**Files:**
- Create: `src/whodex/projection/__init__.py` (empty), `src/whodex/projection/conflict.py`
- Test: `tests/projection/test_conflict.py`

- [ ] **Step 1: Write failing tests for precedence**

Create `tests/projection/test_conflict.py`:
```python
from tests.conftest import _t
from whodex.domain.trust import DEFAULT_TRUST
from whodex.projection.conflict import resolve_field


def _obs_for(field):
    from tests.conftest import obs
    return obs


def test_higher_trust_wins_regardless_of_recency():
    from tests.conftest import obs
    older_high = obs(entity="E1", field="job.title", value="A", source="obsidian", observed=_t(1))
    newer_low = obs(entity="E1", field="job.title", value="B", source="linkedin_ext", observed=_t(9))
    fv, _winner, losers = resolve_field([older_high, newer_low], pinned=None, trust=DEFAULT_TRUST)
    assert fv.value == "A"
    assert losers[0].value == "B"


def test_within_equal_trust_newest_observed_wins():
    from tests.conftest import obs
    old = obs(entity="E1", field="job.title", value="A", source="fake", observed=_t(1))
    new = obs(entity="E1", field="job.title", value="B", source="fake", observed=_t(5))
    fv, _w, _l = resolve_field([old, new], pinned=None, trust=DEFAULT_TRUST)
    assert fv.value == "B"


def test_pin_beats_everything():
    from tests.conftest import obs
    high = obs(entity="E1", field="job.title", value="A", source="obsidian", observed=_t(9))
    fv, winner, _l = resolve_field([high], pinned="PINNED", trust=DEFAULT_TRUST)
    assert fv.value == "PINNED"
    assert fv.pinned is True
    assert winner is None  # pin is not an observation


def test_deterministic_tiebreak_by_id():
    from tests.conftest import obs
    a = obs(entity="E1", field="job.title", value="A", source="fake", observed=_t(1))
    b = obs(entity="E1", field="job.title", value="B", source="fake", observed=_t(1))
    fv1, _, _ = resolve_field([a, b], pinned=None, trust=DEFAULT_TRUST)
    fv2, _, _ = resolve_field([b, a], pinned=None, trust=DEFAULT_TRUST)
    assert fv1.value == fv2.value  # order-independent
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/projection/test_conflict.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `conflict.py`**

Create `src/whodex/projection/__init__.py` (empty), then `src/whodex/projection/conflict.py`:
```python
from __future__ import annotations

from collections.abc import Mapping, Sequence

from whodex.domain.events import Observation
from whodex.domain.state import FieldValue


def _sort_key(o: Observation, trust: Mapping[str, int]) -> tuple:
    return (
        trust.get(o.source_kind, 0),
        o.observed_at,
        o.ingested_at,
        o.confidence,
        o.id,
    )


def resolve_field(
    observations: Sequence[Observation],
    *,
    pinned: object | None,
    trust: Mapping[str, int],
) -> tuple[FieldValue, Observation | None, list[Observation]]:
    """Return (winning FieldValue, winning Observation|None, losing observations).

    Precedence (DESIGN §6.1): pin > trust > observed_at > ingested_at > confidence > id.
    A pin overlay (from a UserAction) beats every observation; the winner Observation is then None.
    """
    if not observations:
        raise ValueError("resolve_field requires at least one observation")
    ordered = sorted(observations, key=lambda o: _sort_key(o, trust))
    winner = ordered[-1]
    losers = ordered[:-1]
    if pinned is not None:
        fv = FieldValue(
            field=winner.field, value=pinned, source_kind="manual_cli",
            observed_at=winner.observed_at, ingested_at=winner.ingested_at, pinned=True,
        )
        return fv, None, list(observations)
    fv = FieldValue(
        field=winner.field, value=winner.value, source_kind=winner.source_kind,
        observed_at=winner.observed_at, ingested_at=winner.ingested_at, pinned=False,
    )
    return fv, winner, losers
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/projection/test_conflict.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the gate and commit**

Run: `uv run mypy --strict src && uv run pytest -q`
Expected: PASS.
```bash
git add src/whodex/projection tests/projection/test_conflict.py
git commit -m "feat(projection): precedence comparator (resolve_field)"
```

---

### Task 9: `projection.project` — the pure fold (+ change §6.4, conflict §6.5)

**Files:**
- Create: `src/whodex/projection/project.py`
- Test: `tests/projection/test_project.py`

- [ ] **Step 1: Write failing tests for the fold semantics**

Create `tests/projection/test_project.py`:
```python
from tests.conftest import _t, action, obs
from whodex.domain.canonical import value_hash
from whodex.domain.enums import EntityKind, ObsOp, UserActionType
from whodex.domain.state import EntityState, EventStream
from whodex.domain.trust import DEFAULT_TRUST
from whodex.projection.project import project

KINDS = {"E1": EntityKind.person}


def _project(events, prev=None):
    return project(events, prev, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(10))


def test_initial_fill_is_not_a_change():
    stream = EventStream(observations=[obs(entity="E1", field="job.title", value="Eng")])
    result = _project(stream)
    assert result.states["E1"].fields["job.title"].value == "Eng"
    assert result.changes == []  # null -> value is an initial fill


def test_value_flip_emits_exactly_one_change():
    first = _project(EventStream(observations=[obs(entity="E1", field="job.title", value="Eng", observed=_t(1))]))
    stream2 = EventStream(observations=[obs(entity="E1", field="job.title", value="Staff Eng", observed=_t(5))])
    result = project(stream2, first.states, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(10))
    assert len(result.changes) == 1
    assert result.changes[0].old_value == "Eng"
    assert result.changes[0].new_value == "Staff Eng"


def test_reproject_same_data_emits_no_change():
    stream = EventStream(observations=[obs(entity="E1", field="job.title", value="Eng")])
    first = _project(stream)
    second = project(stream, first.states, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(10))
    assert second.changes == []


def test_cosmetic_diff_is_not_a_change():
    first = _project(EventStream(observations=[obs(entity="E1", field="job.title", value="Staff Eng", observed=_t(1))]))
    stream2 = EventStream(observations=[obs(entity="E1", field="job.title", value="  Staff   Eng ", observed=_t(5))])
    result = project(stream2, first.states, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(10))
    assert result.changes == []


def test_lower_trust_disagreement_emits_conflict_not_change():
    stream = EventStream(observations=[
        obs(entity="E1", field="job.title", value="Truth", source="obsidian", observed=_t(1)),
        obs(entity="E1", field="job.title", value="Stale", source="linkedin_ext", observed=_t(9)),
    ])
    result = _project(stream)
    assert result.states["E1"].fields["job.title"].value == "Truth"
    assert result.changes == []
    assert len(result.conflict_suggestions) == 1
    assert result.conflict_suggestions[0].reason == "lower_trust_disagrees"


def test_pin_overlay_makes_pinned_value_win():
    stream = EventStream(
        observations=[obs(entity="E1", field="job.title", value="FromSource", source="obsidian")],
        user_actions=[action(action_type=UserActionType.pin, target_type="field",
                             target_id="E1:job.title", entity="E1",
                             payload={"field": "job.title", "value": "Pinned"})],
    )
    result = _project(stream)
    assert result.states["E1"].fields["job.title"].value == "Pinned"
    assert result.states["E1"].fields["job.title"].pinned is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/projection/test_project.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `project.py`**

Create `src/whodex/projection/project.py`:
```python
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime

from whodex.domain.canonical import canonicalize, value_hash
from whodex.domain.enums import EntityKind, Significance, UserActionType
from whodex.domain.fields import field_def
from whodex.domain.state import (
    Change,
    ConflictSuggestion,
    EntityGraphState,
    EntityState,
    EventStream,
    ProjectionResult,
)
from whodex.projection.conflict import resolve_field


def _pins(events: EventStream) -> dict[tuple[str, str], object]:
    """Latest pin value per (entity, field); cleared by unpin."""
    pins: dict[tuple[str, str], object] = {}
    for a in sorted(events.user_actions, key=lambda x: x.created_at):
        if a.action_type == UserActionType.pin and a.entity_id:
            pins[(a.entity_id, a.payload["field"])] = a.payload["value"]
        elif a.action_type == UserActionType.unpin and a.entity_id:
            pins.pop((a.entity_id, a.payload["field"]), None)
    return pins


def _significance(field: str) -> Significance:
    return Significance.notable if field_def(field).volatile else Significance.minor


def project(
    events: EventStream,
    prev: EntityGraphState | None = None,
    *,
    trust: Mapping[str, int],
    kinds: Mapping[str, EntityKind],
    now: datetime,
) -> ProjectionResult:
    """Pure fold: event streams -> entity state + Changes + ConflictSuggestions.

    `kinds` maps entity_id -> EntityKind (resolved upstream by identity resolution).
    `now` stamps detected_at. No IO, no ambient clock.
    """
    prev = prev or {}
    by_field: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for o in events.observations:
        if o.entity_id is None:
            continue
        by_field[o.entity_id][o.field].append(o)

    pins = _pins(events)
    result = ProjectionResult()
    seq = 0

    for entity_id, fields in by_field.items():
        state = EntityState(entity_id=entity_id, kind=kinds.get(entity_id, EntityKind.person))
        for field, obs_list in fields.items():
            pinned = pins.get((entity_id, field))
            fv, winner, losers = resolve_field(obs_list, pinned=pinned, trust=trust)
            state.fields[field] = fv

            # change detection (§6.4): only when the winning *canonical* value flips
            prev_fv = (prev.get(entity_id).fields.get(field) if prev.get(entity_id) else None)
            if prev_fv is not None and winner is not None:
                if canonicalize(field, prev_fv.value) != canonicalize(field, fv.value):
                    seq += 1
                    result.changes.append(
                        Change(
                            id=f"CHG-{seq:06d}", entity_id=entity_id, field=field,
                            old_value=prev_fv.value, new_value=fv.value,
                            caused_by_observation=winner.id, detected_at=now,
                            significance=_significance(field),
                        )
                    )

            # conflict suggestion (§6.5): a non-winning, materially different observation
            if winner is not None:
                win_canon = canonicalize(field, fv.value)
                for loser in losers:
                    if canonicalize(field, loser.value) != win_canon:
                        seq += 1
                        fp = value_hash(field, loser.op, [winner.id, loser.value])
                        result.conflict_suggestions.append(
                            ConflictSuggestion(
                                id=f"CON-{seq:06d}", entity_id=entity_id, field=field,
                                winning_observation_id=winner.id,
                                disagreeing_observation_id=loser.id,
                                reason="lower_trust_disagrees", fingerprint=fp, detected_at=now,
                            )
                        )
                        break  # one suggestion per field is enough for the queue
        if "name.full" in state.fields:
            state.display_name = state.fields["name.full"].value
        result.states[entity_id] = state

    return result
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/projection/test_project.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Add a Hypothesis property test for order-independence**

Append to `tests/projection/test_project.py`:
```python
from hypothesis import given
from hypothesis import strategies as st


@given(values=st.lists(st.text(min_size=1, max_size=5), min_size=1, max_size=6))
def test_projection_is_order_independent(values):
    from tests.conftest import obs
    base = [obs(entity="E1", field="job.title", value=v, observed=_t(i + 1)) for i, v in enumerate(values)]
    forward = project(EventStream(observations=base), None, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(20))
    backward = project(EventStream(observations=list(reversed(base))), None, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(20))
    assert forward.states["E1"].fields["job.title"].value == backward.states["E1"].fields["job.title"].value
```

- [ ] **Step 6: Run the gate and commit**

Run: `uv run mypy --strict src && uv run pytest -q`
Expected: PASS.
```bash
git add src/whodex/projection/project.py tests/projection/test_project.py
git commit -m "feat(projection): pure project() fold with change and conflict detection"
```

---

### Task 10: `sources.base` + `FakeSource`

**Files:**
- Create: `src/whodex/sources/__init__.py` (empty), `src/whodex/sources/base.py`, `src/whodex/sources/fake.py`
- Test: `tests/sources/__init__.py` (empty), `tests/sources/test_fake.py`, `tests/sources/test_source_contract.py`

- [ ] **Step 1: Write failing tests for apply_map + FakeSource**

Create `tests/sources/test_fake.py`:
```python
from tests.conftest import raw
from whodex.sources.base import Capability
from whodex.sources.fake import FakeSource


def test_fake_source_fetches_seeded_records():
    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
    src = FakeSource(records=[r])
    assert list(src.fetch(None)) == [r]
    assert Capability.PULL in src.capabilities


def test_fake_source_normalizes_via_map():
    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
    drafts = FakeSource(records=[r]).normalize(r)
    fields = {d.field: d.value for d in drafts}
    assert fields == {"name.full": "Jane", "job.title": "Eng"}
```

Create `tests/sources/test_source_contract.py`:
```python
"""Reusable contract suite every Source must satisfy (DESIGN §12 L2)."""
import pytest

from tests.conftest import raw
from whodex.sources.fake import FakeSource


@pytest.fixture
def source():
    return FakeSource(records=[raw(identity={"email": "a@b.com"},
                                   payload={"display_name": "Jane", "title": "Eng"})])


def test_normalize_yields_valid_field_drafts(source):
    from whodex.domain.fields import is_valid_field
    for r in source.fetch(None):
        for d in source.normalize(r):
            assert is_valid_field(d.field)


def test_normalize_is_idempotent(source):
    r = next(iter(source.fetch(None)))
    assert source.normalize(r) == source.normalize(r)


def test_id_is_stable_nonempty(source):
    assert isinstance(source.id, str) and source.id
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/sources -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `base.py`**

Create `src/whodex/sources/__init__.py` (empty), then `src/whodex/sources/base.py`:
```python
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from whodex.domain.enums import Capability
from whodex.domain.events import ObservationDraft, RawRecord


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
    source_path: str           # dotted path into payload, e.g. "organizations.0.title"
    canonical: str             # canonical field name
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
        drafts.append(ObservationDraft(field=fm.canonical, value=value, observed_at=record.observed_at))
    return drafts
```

- [ ] **Step 4: Implement `fake.py`**

Create `src/whodex/sources/fake.py`:
```python
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
    id = "fake"
    capabilities = Capability.PULL
    identity_keys = ("email", "name.full")
    provides = (FieldSpec(canonical="name.full"), FieldSpec(canonical="job.title"))

    def __init__(self, records: list[RawRecord]) -> None:
        self._records = records

    def fetch(self, since: datetime | None) -> Iterable[RawRecord]:
        return list(self._records)

    def normalize(self, record: RawRecord) -> list[ObservationDraft]:
        return apply_map(record, _MAP)
```

- [ ] **Step 5: Run to verify passing**

Run: `uv run pytest tests/sources -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Run the gate and commit**

Run: `uv run mypy --strict src && uv run lint-imports && uv run pytest -q`
Expected: PASS; contracts kept.
```bash
git add src/whodex/sources tests/sources
git commit -m "feat(sources): Source protocol, apply_map, FakeSource + contract suite"
```

---

### Task 11: `store` — interfaces + in-memory backend + shared store contract

**Files:**
- Create: `src/whodex/store/__init__.py` (empty), `src/whodex/store/interfaces.py`, `src/whodex/store/memory.py`
- Test: `tests/store/__init__.py` (empty), `tests/store/store_contract.py`, `tests/store/test_memory.py`

- [ ] **Step 1: Write the reusable store-contract suite + in-memory test**

Create `tests/store/store_contract.py`:
```python
"""Behavioural contract every LedgerStore must satisfy. Subclass and set `make_store`."""
from tests.conftest import obs


class LedgerStoreContract:
    def make_store(self):  # override
        raise NotImplementedError

    def test_append_then_read_observations(self):
        store = self.make_store()
        o = obs(entity="E1", field="job.title", value="Eng")
        store.append_observations([o])
        read = store.read_events().observations
        assert len(read) == 1
        assert read[0].id == o.id

    def test_append_is_additive_across_calls(self):
        store = self.make_store()
        store.append_observations([obs(entity="E1", field="email", value="a@b.com")])
        store.append_observations([obs(entity="E1", field="job.title", value="Eng")])
        assert len(store.read_events().observations) == 2

    def test_read_empty_store(self):
        store = self.make_store()
        ev = store.read_events()
        assert ev.observations == [] and ev.interactions == [] and ev.user_actions == []
```

Create `tests/store/test_memory.py`:
```python
from tests.store.store_contract import LedgerStoreContract
from whodex.store.memory import InMemoryLedgerStore


class TestInMemoryLedger(LedgerStoreContract):
    def make_store(self):
        return InMemoryLedgerStore()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/store -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `interfaces.py` and `memory.py`**

Create `src/whodex/store/__init__.py` (empty), then `src/whodex/store/interfaces.py`:
```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.state import EventStream


class LedgerStore(Protocol):
    def append_observations(self, observations: Sequence[Observation]) -> None: ...
    def append_interactions(self, interactions: Sequence[Interaction]) -> None: ...
    def append_user_actions(self, actions: Sequence[UserAction]) -> None: ...
    def read_events(self) -> EventStream: ...


class ProjectionStore(Protocol):
    def save(self, states: dict) -> None: ...
    def load(self) -> dict: ...
```

Create `src/whodex/store/memory.py`:
```python
from __future__ import annotations

from collections.abc import Sequence

from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.state import EntityGraphState, EventStream


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

    def save(self, states: dict) -> None:
        self._states = dict(states)

    def load(self) -> dict:
        return dict(self._states)
```

- [ ] **Step 4: Run to verify passing, then gate + commit**

Run: `uv run mypy --strict src && uv run pytest tests/store -q`
Expected: PASS (3 tests).
```bash
git add src/whodex/store tests/store
git commit -m "feat(store): LedgerStore/ProjectionStore interfaces + in-memory backend"
```

---

### Task 12: `store` — SQLite backend (rows + mappers) under the same contract

**Files:**
- Create: `src/whodex/store/rows.py`, `src/whodex/store/mappers.py`, `src/whodex/store/sqlite.py`
- Test: `tests/store/test_sqlite.py`

- [ ] **Step 1: Write the SQLite store test (reuses the contract)**

Create `tests/store/test_sqlite.py`:
```python
from tests.store.store_contract import LedgerStoreContract
from whodex.store.sqlite import SqliteLedgerStore


class TestSqliteLedger(LedgerStoreContract):
    def make_store(self):
        return SqliteLedgerStore("sqlite://")  # in-memory engine


def test_observation_survives_roundtrip_through_sqlite():
    from tests.conftest import obs
    store = SqliteLedgerStore("sqlite://")
    o = obs(entity="E1", field="job.title", value="Eng")
    store.append_observations([o])
    back = store.read_events().observations[0]
    assert back == o
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/store/test_sqlite.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `rows.py`**

Create `src/whodex/store/rows.py`:
```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ObservationRow(SQLModel, table=True):
    __tablename__ = "observation"
    id: str = Field(primary_key=True)
    source_run_id: str = Field(index=True)
    source_kind: str
    entity_id: str | None = Field(default=None, index=True)
    external_ref: str = Field(index=True)
    external_ref_kind: str
    field: str = Field(index=True)
    op: str
    value: Any = Field(default=None, sa_column=Column(JSON))
    value_hash: str = Field(index=True)
    observed_at: datetime = Field(index=True)
    ingested_at: datetime
    confidence: float = 1.0
    raw_ref: str | None = None


class InteractionRow(SQLModel, table=True):
    __tablename__ = "interaction"
    id: str = Field(primary_key=True)
    kind: str
    occurred_at: datetime
    participant_ids: Any = Field(default=None, sa_column=Column(JSON))
    summary: str | None = None
    source_run_id: str | None = None
    created_at: datetime


class UserActionRow(SQLModel, table=True):
    __tablename__ = "user_action"
    id: str = Field(primary_key=True)
    action_type: str
    target_type: str
    target_id: str = Field(index=True)
    entity_id: str | None = Field(default=None, index=True)
    payload: Any = Field(default=None, sa_column=Column(JSON))
    created_at: datetime
    actor: str = "user"
```

- [ ] **Step 4: Implement `mappers.py`**

Create `src/whodex/store/mappers.py`:
```python
from __future__ import annotations

from whodex.domain.enums import InteractionKind, ObsOp, UserActionType
from whodex.domain.events import Interaction, Observation, UserAction
from whodex.store.rows import InteractionRow, ObservationRow, UserActionRow


def obs_to_row(o: Observation) -> ObservationRow:
    return ObservationRow(**{**o.model_dump(), "op": o.op.value})


def row_to_obs(r: ObservationRow) -> Observation:
    data = r.model_dump()
    data["op"] = ObsOp(data["op"])
    return Observation(**data)


def interaction_to_row(i: Interaction) -> InteractionRow:
    d = i.model_dump()
    d["kind"] = i.kind.value
    d["participant_ids"] = list(i.participant_ids)
    return InteractionRow(**d)


def row_to_interaction(r: InteractionRow) -> Interaction:
    d = r.model_dump()
    d["kind"] = InteractionKind(d["kind"])
    d["participant_ids"] = tuple(d["participant_ids"] or ())
    return Interaction(**d)


def action_to_row(a: UserAction) -> UserActionRow:
    return UserActionRow(**{**a.model_dump(), "action_type": a.action_type.value})


def row_to_action(r: UserActionRow) -> UserAction:
    d = r.model_dump()
    d["action_type"] = UserActionType(d["action_type"])
    return UserAction(**d)
```

- [ ] **Step 5: Implement `sqlite.py`**

Create `src/whodex/store/sqlite.py`:
```python
from __future__ import annotations

from collections.abc import Sequence

from sqlmodel import Session, SQLModel, create_engine, select

from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.state import EventStream
from whodex.store import mappers
from whodex.store.rows import InteractionRow, ObservationRow, UserActionRow


class SqliteLedgerStore:
    def __init__(self, url: str = "sqlite://") -> None:
        self._engine = create_engine(url)
        SQLModel.metadata.create_all(self._engine)

    def append_observations(self, observations: Sequence[Observation]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.obs_to_row(o) for o in observations])
            s.commit()

    def append_interactions(self, interactions: Sequence[Interaction]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.interaction_to_row(i) for i in interactions])
            s.commit()

    def append_user_actions(self, actions: Sequence[UserAction]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.action_to_row(a) for a in actions])
            s.commit()

    def read_events(self) -> EventStream:
        with Session(self._engine) as s:
            obs = [mappers.row_to_obs(r) for r in s.exec(select(ObservationRow)).all()]
            ints = [mappers.row_to_interaction(r) for r in s.exec(select(InteractionRow)).all()]
            acts = [mappers.row_to_action(r) for r in s.exec(select(UserActionRow)).all()]
        return EventStream(observations=obs, interactions=ints, user_actions=acts)
```

- [ ] **Step 6: Run to verify passing, then gate + commit**

Run: `uv run mypy --strict src && uv run lint-imports && uv run pytest tests/store -q`
Expected: PASS (in-memory and SQLite pass the same contract).
```bash
git add src/whodex/store/rows.py src/whodex/store/mappers.py src/whodex/store/sqlite.py tests/store/test_sqlite.py
git commit -m "feat(store): SQLite ledger backend (rows + mappers) under shared contract"
```

---

### Task 13: `sync.hub` — ObservationFactory, IdentityResolver, IngestionHub

**Files:**
- Create: `src/whodex/sync/__init__.py` (empty), `src/whodex/sync/hub.py`
- Test: `tests/sync/__init__.py` (empty), `tests/sync/test_hub.py`

- [ ] **Step 1: Write failing tests**

Create `tests/sync/test_hub.py`:
```python
from tests.conftest import raw
from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.sync.hub import IdentityResolver, IngestionHub


def _hub():
    from datetime import UTC, datetime
    return IngestionHub(
        ids=SequentialIdFactory("OBS"),
        clock=FixedClock(datetime(2026, 2, 1, tzinfo=UTC)),
        identity=IdentityResolver(SequentialIdFactory("E")),
    )


def test_hub_resolves_new_entity_and_finalizes_observations():
    hub = _hub()
    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})
    from whodex.sources.fake import FakeSource
    result = hub.ingest(FakeSource(records=[r]), r, source_run_id="RUN-1")
    assert result.entity_id == "E-00000001"
    assert all(o.entity_id == "E-00000001" for o in result.observations)
    assert all(o.ingested_at.year == 2026 for o in result.observations)
    assert {o.field for o in result.observations} == {"name.full", "job.title"}


def test_hub_reuses_entity_for_same_identity():
    hub = _hub()
    from whodex.sources.fake import FakeSource
    r = raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane"})
    first = hub.ingest(FakeSource(records=[r]), r, source_run_id="RUN-1")
    second = hub.ingest(FakeSource(records=[r]), r, source_run_id="RUN-2")
    assert first.entity_id == second.entity_id
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/sync/test_hub.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `hub.py`**

Create `src/whodex/sync/__init__.py` (empty), then `src/whodex/sync/hub.py`:
```python
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

    def _finalize(self, draft: ObservationDraft, *, record: RawRecord, entity_id: str,
                  source_kind: str, source_run_id: str, external_ref: str) -> Observation:
        if not is_valid_field(draft.field):
            raise ValueError(f"unknown field: {draft.field}")
        observed_at = draft.observed_at or record.observed_at
        return Observation(
            id=self._ids.new(), source_run_id=source_run_id, source_kind=source_kind,
            entity_id=entity_id, external_ref=external_ref,
            external_ref_kind=next(iter(record.identity), "unknown"),
            field=draft.field, op=draft.op, value=draft.value,
            value_hash=value_hash(draft.field, draft.op, draft.value),
            observed_at=observed_at, ingested_at=self._clock.now(), confidence=draft.confidence,
        )

    def ingest(self, source: Source, record: RawRecord, *, source_run_id: str) -> IngestResult:
        entity_id = self.identity.resolve(record.identity)
        external_ref = self.identity.primary_ref(record.identity)
        obs = [
            self._finalize(d, record=record, entity_id=entity_id, source_kind=source.id,
                           source_run_id=source_run_id, external_ref=external_ref)
            for d in source.normalize(record)
        ]
        return IngestResult(entity_id=entity_id, observations=obs)
```

Note: `ingest` keyword-only `source_run_id` — the test calls `hub.ingest(src, r, source_run_id="RUN-1")`.

- [ ] **Step 4: Run to verify passing, then gate + commit**

Run: `uv run mypy --strict src && uv run lint-imports && uv run pytest tests/sync -q`
Expected: PASS (2 tests).
```bash
git add src/whodex/sync/hub.py tests/sync/test_hub.py
git commit -m "feat(sync): ingestion hub with identity resolution and observation factory"
```

---

### Task 14: `sync.engine` — `run_sync` orchestration

**Files:**
- Create: `src/whodex/sync/engine.py`
- Test: `tests/sync/test_engine.py`

- [ ] **Step 1: Write failing tests**

Create `tests/sync/test_engine.py`:
```python
from datetime import UTC, datetime

from tests.conftest import raw
from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.domain.trust import DEFAULT_TRUST
from whodex.sources.fake import FakeSource
from whodex.store.memory import InMemoryLedgerStore, InMemoryProjectionStore
from whodex.sync.engine import run_sync
from whodex.sync.hub import IdentityResolver, IngestionHub


def _wiring():
    ledger = InMemoryLedgerStore()
    proj = InMemoryProjectionStore()
    hub = IngestionHub(ids=SequentialIdFactory("OBS"),
                       clock=FixedClock(datetime(2026, 2, 1, tzinfo=UTC)),
                       identity=IdentityResolver(SequentialIdFactory("E")))
    return ledger, proj, hub


def test_run_sync_materializes_state():
    ledger, proj, hub = _wiring()
    src = FakeSource(records=[raw(identity={"email": "a@b.com"},
                                  payload={"display_name": "Jane", "title": "Eng"})])
    report = run_sync([src], ledger=ledger, projection=proj, hub=hub,
                      trust=DEFAULT_TRUST, now=datetime(2026, 2, 1, tzinfo=UTC))
    state = proj.load()
    assert state["E-00000001"].fields["job.title"].value == "Eng"
    assert report.observations_ingested == 2
    assert report.changes == 0  # initial fill


def test_rerun_is_idempotent_no_changes():
    ledger, proj, hub = _wiring()
    src = FakeSource(records=[raw(identity={"email": "a@b.com"}, payload={"title": "Eng"})])
    run_sync([src], ledger=ledger, projection=proj, hub=hub, trust=DEFAULT_TRUST,
             now=datetime(2026, 2, 1, tzinfo=UTC))
    report2 = run_sync([src], ledger=ledger, projection=proj, hub=hub, trust=DEFAULT_TRUST,
                       now=datetime(2026, 2, 2, tzinfo=UTC))
    assert report2.changes == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/sync/test_engine.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `engine.py`**

Create `src/whodex/sync/engine.py`:
```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from whodex.projection.project import project
from whodex.sources.base import PullSource
from whodex.store.interfaces import LedgerStore, ProjectionStore
from whodex.sync.hub import IngestionHub


@dataclass
class SyncReport:
    observations_ingested: int = 0
    changes: int = 0
    conflicts: int = 0


def run_sync(
    sources: Sequence[PullSource],
    *,
    ledger: LedgerStore,
    projection: ProjectionStore,
    hub: IngestionHub,
    trust: Mapping[str, int],
    now: datetime,
) -> SyncReport:
    report = SyncReport()
    run_seq = 0
    for source in sources:
        run_seq += 1
        run_id = f"RUN-{run_seq}"
        for record in source.fetch(None):
            result = hub.ingest(source, record, source_run_id=run_id)
            ledger.append_observations(result.observations)
            report.observations_ingested += len(result.observations)

    prev = projection.load()
    events = ledger.read_events()
    proj = project(events, prev or None, trust=trust, kinds=hub.identity.kinds, now=now)
    projection.save(proj.states)
    report.changes = len(proj.changes)
    report.conflicts = len(proj.conflict_suggestions)
    return report
```

- [ ] **Step 4: Run to verify passing, then gate + commit**

Run: `uv run mypy --strict src && uv run lint-imports && uv run pytest tests/sync -q`
Expected: PASS.
```bash
git add src/whodex/sync/engine.py tests/sync/test_engine.py
git commit -m "feat(sync): run_sync orchestration (fetch -> ingest -> ledger -> project)"
```

---

### Task 15: `config` composition root + `cli` (`whodex sync`)

**Files:**
- Create: `src/whodex/config/__init__.py` (empty), `src/whodex/config/settings.py`, `src/whodex/cli/__init__.py` (empty), `src/whodex/cli/main.py`
- Test: `tests/cli/__init__.py` (empty), `tests/cli/test_sync.py`

- [ ] **Step 1: Write failing test for the CLI**

Create `tests/cli/test_sync.py`:
```python
from typer.testing import CliRunner

from whodex.cli.main import app

runner = CliRunner()


def test_sync_runs_with_demo_source_and_prints_state():
    result = runner.invoke(app, ["sync", "--demo"])
    assert result.exit_code == 0
    assert "Jane Demo" in result.stdout
    assert "job.title" in result.stdout
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/cli/test_sync.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `config/settings.py`**

Create `src/whodex/config/__init__.py` (empty), then `src/whodex/config/settings.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from whodex.domain.clock import Clock, SystemClock
from whodex.domain.ids import IdFactory, UlidIdFactory
from whodex.domain.trust import DEFAULT_TRUST
from whodex.sources.base import PullSource
from whodex.sources.fake import FakeSource
from whodex.domain.events import RawRecord
from whodex.store.memory import InMemoryLedgerStore, InMemoryProjectionStore
from whodex.sync.hub import IdentityResolver, IngestionHub


@dataclass
class App:
    ledger: InMemoryLedgerStore
    projection: InMemoryProjectionStore
    hub: IngestionHub
    sources: list[PullSource]
    trust: dict[str, int]
    clock: Clock


def build_app(*, demo: bool = False, ids: IdFactory | None = None, clock: Clock | None = None) -> App:
    ids = ids or UlidIdFactory()
    clock = clock or SystemClock()
    sources: list[PullSource] = []
    if demo:
        sources.append(
            FakeSource(records=[RawRecord(
                source="fake", identity={"email": "jane@demo.com"},
                payload={"display_name": "Jane Demo", "title": "Founder"},
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            )])
        )
    return App(
        ledger=InMemoryLedgerStore(),
        projection=InMemoryProjectionStore(),
        hub=IngestionHub(ids=ids, clock=clock, identity=IdentityResolver(UlidIdFactory())),
        sources=sources,
        trust=dict(DEFAULT_TRUST),
        clock=clock,
    )
```

- [ ] **Step 4: Implement `cli/main.py`**

Create `src/whodex/cli/__init__.py` (empty), then `src/whodex/cli/main.py`:
```python
from __future__ import annotations

import typer

from whodex.config.settings import build_app
from whodex.sync.engine import run_sync

app = typer.Typer(help="whodex — local-first people CRM")


@app.command()
def sync(demo: bool = typer.Option(False, "--demo", help="run with a built-in demo source")) -> None:
    """Run one sync pass and print the projected state."""
    wiring = build_app(demo=demo)
    report = run_sync(
        wiring.sources, ledger=wiring.ledger, projection=wiring.projection,
        hub=wiring.hub, trust=wiring.trust, now=wiring.clock.now(),
    )
    typer.echo(f"ingested={report.observations_ingested} changes={report.changes} "
               f"conflicts={report.conflicts}")
    for eid, state in wiring.projection.load().items():
        typer.echo(f"- {state.display_name or eid} ({state.kind.value})")
        for fname, fv in sorted(state.fields.items()):
            typer.echo(f"    {fname}: {fv.value}  [{fv.source_kind}]")
```

- [ ] **Step 5: Run to verify passing, then gate + commit**

Run: `uv run mypy --strict src && uv run lint-imports && uv run pytest tests/cli -q`
Expected: PASS; the `--demo` run prints `Jane Demo` and `job.title: Founder`.
```bash
git add src/whodex/config src/whodex/cli tests/cli
git commit -m "feat(cli): whodex sync command + composition root"
```

---

### Task 16: Acceptance — the §13 "Done when" e2e + SQLite≡in-memory parity

**Files:**
- Test: `tests/test_e2e_phase0.py`

- [ ] **Step 1: Write the end-to-end acceptance test**

Create `tests/test_e2e_phase0.py`:
```python
from datetime import UTC, datetime

import pytest

from tests.conftest import raw
from whodex.domain.clock import FixedClock
from whodex.domain.ids import SequentialIdFactory
from whodex.domain.trust import DEFAULT_TRUST
from whodex.sources.fake import FakeSource
from whodex.store.memory import InMemoryLedgerStore, InMemoryProjectionStore
from whodex.store.sqlite import SqliteLedgerStore
from whodex.sync.engine import run_sync
from whodex.sync.hub import IdentityResolver, IngestionHub


def _hub():
    return IngestionHub(ids=SequentialIdFactory("OBS"),
                        clock=FixedClock(datetime(2026, 2, 1, tzinfo=UTC)),
                        identity=IdentityResolver(SequentialIdFactory("E")))


@pytest.mark.e2e
def test_job_change_produces_exactly_one_change_and_none_on_rerun():
    ledger, proj, hub = InMemoryLedgerStore(), InMemoryProjectionStore(), _hub()
    first_src = FakeSource(records=[raw(identity={"email": "a@b.com"},
                                        payload={"display_name": "Jane", "title": "Engineer"},
                                        observed=datetime(2026, 1, 1, tzinfo=UTC))])
    r1 = run_sync([first_src], ledger=ledger, projection=proj, hub=hub,
                  trust=DEFAULT_TRUST, now=datetime(2026, 2, 1, tzinfo=UTC))
    assert r1.changes == 0  # initial fill

    change_src = FakeSource(records=[raw(identity={"email": "a@b.com"},
                                         payload={"display_name": "Jane", "title": "Staff Engineer"},
                                         observed=datetime(2026, 1, 15, tzinfo=UTC))])
    r2 = run_sync([change_src], ledger=ledger, projection=proj, hub=hub,
                  trust=DEFAULT_TRUST, now=datetime(2026, 2, 2, tzinfo=UTC))
    assert r2.changes == 1
    assert proj.load()["E-00000001"].fields["job.title"].value == "Staff Engineer"

    r3 = run_sync([change_src], ledger=ledger, projection=proj, hub=hub,
                  trust=DEFAULT_TRUST, now=datetime(2026, 2, 3, tzinfo=UTC))
    assert r3.changes == 0  # no spurious change/suggestion on re-run


@pytest.mark.e2e
def test_sqlite_and_memory_materialize_identically():
    records = [raw(identity={"email": "a@b.com"}, payload={"display_name": "Jane", "title": "Eng"})]

    def project_with(ledger):
        proj = InMemoryProjectionStore()
        run_sync([FakeSource(records=records)], ledger=ledger, projection=proj, hub=_hub(),
                 trust=DEFAULT_TRUST, now=datetime(2026, 2, 1, tzinfo=UTC))
        return proj.load()

    mem = project_with(InMemoryLedgerStore())
    sql = project_with(SqliteLedgerStore("sqlite://"))
    assert mem.keys() == sql.keys()
    assert mem["E-00000001"].fields["job.title"].value == sql["E-00000001"].fields["job.title"].value
```

- [ ] **Step 2: Run the acceptance tests**

Run: `uv run pytest tests/test_e2e_phase0.py -q`
Expected: PASS (2 tests).

- [ ] **Step 3: Run the FULL gate (the Phase-0 definition of done)**

Run: `uv run ruff format --check . && uv run ruff check . && uv run mypy --strict src && uv run lint-imports && uv run pytest -q --cov=whodex`
Expected: all green; both import-linter contracts kept; coverage reported.

- [ ] **Step 4: Commit and open PR**

```bash
git add tests/test_e2e_phase0.py
git commit -m "test(e2e): Phase-0 acceptance — job-change change-detection + store parity"
git push -u origin phase-0-walking-skeleton
```

---

## Self-review (completed against DESIGN §13 Phase 0)

**Spec coverage:**
- Scaffolding (uv/hatchling/ruff/mypy/import-linter/CI) → Task 1 ✓
- domain models (Entity*/Observation/ObservationDraft/Interaction/UserAction/states/Change/ConflictSuggestion/GraphRepairSuggestion/Clock/IdFactory/fields ~20) → Tasks 2–6 ✓ (`Entity`/`ContactProfileState` row persistence beyond `EntityState` is Phase-1; the projected `EntityState` + `ContactProfileState` struct exist)
- `project()` pure fold + comparator + change §6.4 + conflict §6.5 → Tasks 8–9 ✓; graph-repair rules **deferred** (documented in Scope)
- in-memory + SQLite stores under one interface → Tasks 11–12 ✓
- `Source`/`Capability` + `apply_map` + `FakeSource` → Task 10 ✓
- `sync.run_sync` wiring → Tasks 13–14 ✓
- `whodex sync` CLI prints state → Task 15 ✓
- `obs()/interaction()/action()` DSL + L1 tests + `SourceContract` skeleton → Tasks 7, 8–10 ✓
- "Done when" (idempotent ≤1 change, SQLite≡in-memory, gates green) → Task 16 ✓

**Deferred (explicitly, see Scope):** edge projection, graph-repair rules, JSONL mirror — all Phase 1.

**Type consistency:** `resolve_field` signature, `project(events, prev, *, trust, kinds, now)`, `IngestionHub.ingest(source, record, *, source_run_id)`, `run_sync(...)`, `EntityState.fields[name].value`, and the builders in `conftest.py` are referenced identically across tasks.

**Placeholder scan:** no TBD/TODO; every code step shows complete code; every run step gives an exact command + expected result.
