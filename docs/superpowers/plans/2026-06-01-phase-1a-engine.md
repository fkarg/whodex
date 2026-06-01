# whodex Phase 1a — Engine (Prioritization · Freshness · Reminders) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add the pure decision engine on top of the Phase-0 projection: a ranked reach-out priority queue with a human-readable *why-now*, per-field freshness/staleness, and idempotent reminders — all pure functions over projected state + the ledger, exposed via a `whodex queue` CLI command.

**Architecture:** `engine/` holds pure functions (no IO, injected `now`/ids). `build_score_inputs` derives, from the projected `EntityState` map + the `EventStream` (interactions for last-contact, user-actions for pin/snooze/cadence), a list of `ScoreInput`s; `score_contact` turns each into an explainable `Score`; `staleness` classifies field freshness; `generate_reminders` turns scores into deduplicated `Reminder`s. The engine reads only domain types — never connectors or stores.

**Tech Stack:** Python 3.12, pydantic, pytest + hypothesis. Same gate as Phase 0.

---

## Scope

In: `ReminderReason`/`Staleness` enums + domain `Reminder`; `engine.scoring` (`ScoreInput`, `Score`, `ScoringConfig`, `score_contact`, `build_score_inputs`); `engine.freshness` (`FreshnessConfig`, `staleness`); `engine.reminders` (`generate_reminders`); `engine.queue` (`priority_queue`); a `whodex queue --demo` CLI command.

Deferred (later Phase-1 increments): `event_boost` from *persisted* changes (the formula supports it via `ScoreInput.open_change_kinds`, but nothing persists changes yet, so it's exercised only by unit tests with explicit inputs); reminder persistence/notification dispatch; freshness re-check task queue.

**Conventions (every task):** TDD (red → green → commit). Full gate before each commit: `uv run ruff format . && uv run ruff check . && uv run mypy --strict src && uv run lint-imports && uv run pytest -q`. **No `Co-Authored-By` trailer.** `engine` imports only `whodex.domain`. Inject `now`/`IdFactory` — never read the clock ambiently.

## File structure

```
src/whodex/
├── domain/
│   ├── enums.py        # + ReminderReason, Staleness
│   └── state.py        # + Reminder
└── engine/
    ├── scoring.py      # ScoreInput, Score, ScoringConfig, score_contact, build_score_inputs
    ├── freshness.py    # FreshnessConfig, staleness
    ├── reminders.py    # generate_reminders
    └── queue.py        # priority_queue
src/whodex/cli/main.py  # + `queue` command
```

---

### Task 1: enums (`ReminderReason`, `Staleness`) + domain `Reminder`

**Files:** Modify `src/whodex/domain/enums.py`, `src/whodex/domain/state.py`; Test `tests/domain/test_reminder.py`.

- [ ] **Step 1: Append to `src/whodex/domain/enums.py`** (use `StrEnum`, project convention)

```python
class ReminderReason(StrEnum):
    cadence_lapsed = "cadence_lapsed"
    data_stale = "data_stale"
    change_detected = "change_detected"
    manual = "manual"


class Staleness(StrEnum):
    fresh = "fresh"
    stale = "stale"
    expired = "expired"
```
(Note: `enums.py` already uses `StrEnum`/`Flag` and imports `from enum import Flag, StrEnum, auto` — keep that import line correct.)

- [ ] **Step 2: Write `tests/domain/test_reminder.py`**

```python
from datetime import UTC, datetime

from whodex.domain.enums import ReminderReason
from whodex.domain.state import Reminder


def test_reminder_construction():
    r = Reminder(
        id="REM-1", entity_id="E1", due_at=datetime(2026, 2, 1, tzinfo=UTC),
        reason=ReminderReason.cadence_lapsed, fingerprint="fp", score=2.5,
        why=["3.0x overdue"], created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert r.reason == ReminderReason.cadence_lapsed
    assert r.why == ["3.0x overdue"]
```

- [ ] **Step 3: Run `uv run pytest tests/domain/test_reminder.py -q` → expect FAIL.**

- [ ] **Step 4: Append `Reminder` to `src/whodex/domain/state.py`** (import `ReminderReason` from enums at top; place the class after `ConflictSuggestion`)

```python
class Reminder(BaseModel):
    id: str
    entity_id: str
    due_at: datetime
    reason: ReminderReason
    fingerprint: str            # hash of (entity, sorted reasons) — anti-spam dedup key
    score: float
    why: list[str]
    created_at: datetime
```
(Add `ReminderReason` to the existing `from whodex.domain.enums import ...` line in `state.py`.)

- [ ] **Step 5: Run gate and commit**

```bash
uv run pytest tests/domain -q
git add src/whodex/domain/enums.py src/whodex/domain/state.py tests/domain/test_reminder.py
git commit -m "feat(domain): add ReminderReason/Staleness enums and Reminder model"
```

---

### Task 2: `engine.scoring` — `score_contact` (the pure, explainable ranker)

**Files:** Create `src/whodex/engine/scoring.py`; Test `tests/engine/__init__.py` (empty), `tests/engine/test_scoring.py`.

- [ ] **Step 1: Write `tests/engine/test_scoring.py`**

```python
from datetime import UTC, datetime, timedelta

from whodex.engine.scoring import ScoreInput, ScoringConfig, score_contact

NOW = datetime(2026, 3, 1, tzinfo=UTC)
CFG = ScoringConfig()


def _si(**kw):
    base = dict(entity_id="E1", display_name="Jane", last_interaction_at=None,
                cadence_days=30, tier="loose", pinned=False, snoozed_until=None,
                open_change_kinds=())
    base.update(kw)
    return ScoreInput(**base)


def test_snoozed_contact_is_excluded():
    s = score_contact(_si(snoozed_until=NOW + timedelta(days=5)), CFG, NOW)
    assert s.value == float("-inf")
    assert "snoozed" in s.reasons


def test_overdue_drives_score_and_is_capped():
    # 300 days since contact, cadence 30 => ratio 10, capped at overdue_cap (3.0)
    s = score_contact(_si(last_interaction_at=NOW - timedelta(days=300)), CFG, NOW)
    assert s.value == CFG.w_overdue * CFG.overdue_cap  # tier_weight loose = 1.0
    assert any("overdue" in r for r in s.reasons)


def test_never_contacted_is_treated_as_max_overdue():
    s = score_contact(_si(last_interaction_at=None), CFG, NOW)
    assert s.value == CFG.w_overdue * CFG.overdue_cap


def test_tier_multiplies():
    inner = score_contact(_si(last_interaction_at=NOW - timedelta(days=60), tier="inner"), CFG, NOW)
    loose = score_contact(_si(last_interaction_at=NOW - timedelta(days=60), tier="loose"), CFG, NOW)
    assert inner.value > loose.value


def test_pin_floors_the_score():
    # well within cadence => low base, but pinned lifts to pin_floor
    s = score_contact(_si(last_interaction_at=NOW, pinned=True), CFG, NOW)
    assert s.value >= CFG.pin_floor
    assert "pinned" in s.reasons
```

- [ ] **Step 2: Run `uv run pytest tests/engine/test_scoring.py -q` → expect FAIL.**

- [ ] **Step 3: Implement `src/whodex/engine/scoring.py`** (the `ScoreInput`/`Score`/`ScoringConfig` + `score_contact`; `build_score_inputs` is added in Task 3 — define a stub-free module now containing only these)

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ScoreInput(BaseModel):
    entity_id: str
    display_name: str | None
    last_interaction_at: datetime | None
    cadence_days: int
    tier: str
    pinned: bool = False
    snoozed_until: datetime | None = None
    open_change_kinds: tuple[str, ...] = ()


class Score(BaseModel):
    value: float
    reasons: list[str] = Field(default_factory=list)


def _default_tier_weight() -> dict[str, float]:
    return {"inner": 2.0, "close": 1.3, "loose": 1.0}


def _default_cadence() -> dict[str, int]:
    return {"inner": 30, "close": 90, "loose": 180}


def _default_event_weight() -> dict[str, float]:
    return {"job.title": 1.0, "job.org": 1.0, "person.organisations": 1.0, "person.lives": 0.7}


class ScoringConfig(BaseModel):
    w_overdue: float = 1.0
    w_event: float = 0.5
    overdue_cap: float = 3.0
    pin_floor: float = 1000.0
    reminder_threshold: float = 1.0
    tier_weight: dict[str, float] = Field(default_factory=_default_tier_weight)
    cadence_default: dict[str, int] = Field(default_factory=_default_cadence)
    event_weight: dict[str, float] = Field(default_factory=_default_event_weight)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def score_contact(si: ScoreInput, cfg: ScoringConfig, now: datetime) -> Score:
    """Pure, explainable rank. Higher = reach out sooner. Snoozed => -inf (excluded)."""
    if si.snoozed_until is not None and si.snoozed_until > now:
        return Score(value=float("-inf"), reasons=["snoozed"])

    reasons: list[str] = []
    if si.last_interaction_at is None:
        overdue_ratio = cfg.overdue_cap
        reasons.append("never contacted")
    else:
        days = (now - si.last_interaction_at).days
        overdue_ratio = days / si.cadence_days if si.cadence_days > 0 else 0.0
        reasons.append(f"{overdue_ratio:.1f}x overdue ({days}d / {si.cadence_days}d cadence)")
    overdue_ratio = _clamp(overdue_ratio, 0.0, cfg.overdue_cap)

    event_boost = sum(cfg.event_weight.get(k, 0.5) for k in si.open_change_kinds)
    if event_boost:
        reasons.append(f"recent change ({', '.join(si.open_change_kinds)})")

    tier_weight = cfg.tier_weight.get(si.tier, 1.0)
    base = (cfg.w_overdue * overdue_ratio + cfg.w_event * event_boost) * tier_weight
    if si.tier != "loose":
        reasons.append(f"tier={si.tier}")

    value = base
    if si.pinned:
        value = max(base, cfg.pin_floor)
        reasons.append("pinned")
    return Score(value=value, reasons=reasons)
```

- [ ] **Step 4: Run `uv run pytest tests/engine/test_scoring.py -q` → expect PASS (5 tests).**

- [ ] **Step 5: Full gate (paste output) and commit**

```bash
git add src/whodex/engine/scoring.py tests/engine/__init__.py tests/engine/test_scoring.py
git commit -m "feat(engine): explainable score_contact prioritization function"
```

---

### Task 3: `engine.scoring.build_score_inputs` — derive inputs from projection + ledger

**Files:** Modify `src/whodex/engine/scoring.py`; Test `tests/engine/test_score_inputs.py`.

`build_score_inputs` reads the projected `EntityState` map (for kind/display_name/cadence/tier fields) and the `EventStream` (interactions → last_interaction_at; user-actions → pin/snooze) and emits one `ScoreInput` per **person** entity.

Derivation rules:
- Only `EntityKind.person` entities.
- `last_interaction_at` = max `occurred_at` over interactions whose `participant_ids` include the entity, else None.
- `cadence_days` = `int(fields["person.cadence_days"].value)` if present, else `cfg.cadence_default[tier]` (default tier "loose" → 180).
- `tier` = `str(fields["person.importance"].value)` if present and in `cfg.tier_weight`, else "loose".
- `pinned` = there is a `UserAction(action_type=pin, target_type="contact", entity_id=E)` with no later `unpin` for the same entity.
- `snoozed_until` = the latest `UserAction(action_type=snooze, entity_id=E)`'s `payload["until"]` (ISO string → datetime) if in the future-or-any (engine compares to `now`), else None. Use the action with the max `created_at`.

- [ ] **Step 1: Write `tests/engine/test_score_inputs.py`**

```python
from datetime import UTC, datetime

from tests.conftest import action, interaction, obs
from whodex.domain.enums import EntityKind, InteractionKind, UserActionType
from whodex.domain.state import EntityState, EventStream, FieldValue
from whodex.engine.scoring import ScoringConfig, build_score_inputs

NOW = datetime(2026, 3, 1, tzinfo=UTC)
CFG = ScoringConfig()


def _person_state(eid="E1", name="Jane", fields=None):
    return EntityState(entity_id=eid, kind=EntityKind.person, display_name=name, fields=fields or {})


def _fv(field, value):
    return FieldValue(field=field, value=value, source_kind="obsidian", observed_at=NOW, ingested_at=NOW)


def test_builds_one_input_per_person_with_last_interaction():
    states = {"E1": _person_state()}
    events = EventStream(interactions=[
        interaction(entities=("E1",), kind=InteractionKind.met, occurred=datetime(2026, 1, 1, tzinfo=UTC)),
        interaction(entities=("E1",), kind=InteractionKind.call, occurred=datetime(2026, 2, 1, tzinfo=UTC)),
    ])
    inputs = build_score_inputs(states, events, cfg=CFG, now=NOW)
    assert len(inputs) == 1
    assert inputs[0].last_interaction_at == datetime(2026, 2, 1, tzinfo=UTC)  # most recent


def test_cadence_and_tier_from_fields_else_defaults():
    states = {"E1": _person_state(fields={
        "person.cadence_days": _fv("person.cadence_days", 45),
        "person.importance": _fv("person.importance", "inner"),
    })}
    si = build_score_inputs(states, EventStream(), cfg=CFG, now=NOW)[0]
    assert si.cadence_days == 45
    assert si.tier == "inner"

    bare = build_score_inputs({"E2": _person_state(eid="E2")}, EventStream(), cfg=CFG, now=NOW)[0]
    assert bare.tier == "loose"
    assert bare.cadence_days == CFG.cadence_default["loose"]


def test_non_person_entities_are_skipped():
    org = EntityState(entity_id="O1", kind=EntityKind.organisation, display_name="Kolai")
    inputs = build_score_inputs({"O1": org}, EventStream(), cfg=CFG, now=NOW)
    assert inputs == []


def test_pin_and_snooze_from_user_actions():
    states = {"E1": _person_state()}
    events = EventStream(user_actions=[
        action(action_type=UserActionType.pin, target_type="contact", target_id="E1", entity="E1"),
        action(action_type=UserActionType.snooze, target_type="contact", target_id="E1", entity="E1",
               payload={"until": "2026-04-01T00:00:00+00:00"}),
    ])
    si = build_score_inputs(states, events, cfg=CFG, now=NOW)[0]
    assert si.pinned is True
    assert si.snoozed_until == datetime(2026, 4, 1, tzinfo=UTC)
```

- [ ] **Step 2: Run → expect FAIL (no `build_score_inputs`).**

- [ ] **Step 3: Append `build_score_inputs` to `src/whodex/engine/scoring.py`**

```python
# add to imports at top:
# from collections.abc import Mapping
# from whodex.domain.enums import EntityKind, UserActionType
# from whodex.domain.state import EntityGraphState, EventStream


def _latest_interaction(entity_id: str, events: EventStream) -> datetime | None:
    times = [i.occurred_at for i in events.interactions if entity_id in i.participant_ids]
    return max(times) if times else None


def _pin_and_snooze(entity_id: str, events: EventStream) -> tuple[bool, datetime | None]:
    pinned = False
    snoozed_until: datetime | None = None
    for a in sorted(events.user_actions, key=lambda x: x.created_at):
        if a.entity_id != entity_id:
            continue
        if a.action_type == UserActionType.pin and a.target_type == "contact":
            pinned = True
        elif a.action_type == UserActionType.unpin and a.target_type == "contact":
            pinned = False
        elif a.action_type == UserActionType.snooze:
            raw = a.payload.get("until")
            snoozed_until = datetime.fromisoformat(raw) if raw else None
    return pinned, snoozed_until


def build_score_inputs(
    states: EntityGraphState, events: EventStream, *, cfg: ScoringConfig, now: datetime
) -> list[ScoreInput]:
    inputs: list[ScoreInput] = []
    for entity_id, state in states.items():
        if state.kind != EntityKind.person:
            continue
        tier_fv = state.fields.get("person.importance")
        tier = str(tier_fv.value) if tier_fv and str(tier_fv.value) in cfg.tier_weight else "loose"
        cad_fv = state.fields.get("person.cadence_days")
        cadence_days = int(cad_fv.value) if cad_fv is not None else cfg.cadence_default[tier]
        pinned, snoozed_until = _pin_and_snooze(entity_id, events)
        inputs.append(ScoreInput(
            entity_id=entity_id, display_name=state.display_name,
            last_interaction_at=_latest_interaction(entity_id, events),
            cadence_days=cadence_days, tier=tier, pinned=pinned, snoozed_until=snoozed_until,
        ))
    return inputs
```
(`Mapping` import may be unused — only add imports you actually use; `EntityGraphState` is the annotation type. Ensure `mypy --strict` passes: `datetime.fromisoformat` returns `datetime`.)

- [ ] **Step 4: Run → expect PASS (4 tests). Full gate, commit:**

```bash
git add src/whodex/engine/scoring.py tests/engine/test_score_inputs.py
git commit -m "feat(engine): build_score_inputs derives ranking inputs from projection + ledger"
```

---

### Task 4: `engine.freshness` — per-field staleness

**Files:** Create `src/whodex/engine/freshness.py`; Test `tests/engine/test_freshness.py`.

- [ ] **Step 1: Write `tests/engine/test_freshness.py`**

```python
from datetime import UTC, datetime, timedelta

from whodex.domain.enums import Staleness
from whodex.engine.freshness import FreshnessConfig, staleness

NOW = datetime(2026, 3, 1, tzinfo=UTC)
CFG = FreshnessConfig(ttl_days={"job.title": 90, "email": 365, "birthday": 0}, grace_factor=2.0)


def test_fresh_within_ttl():
    assert staleness("job.title", NOW - timedelta(days=30), CFG, NOW) == Staleness.fresh


def test_stale_past_ttl_within_grace():
    assert staleness("job.title", NOW - timedelta(days=120), CFG, NOW) == Staleness.stale


def test_expired_past_grace():
    assert staleness("job.title", NOW - timedelta(days=200), CFG, NOW) == Staleness.expired


def test_ttl_zero_never_stale():
    assert staleness("birthday", NOW - timedelta(days=9999), CFG, NOW) == Staleness.fresh


def test_unconfigured_field_defaults_fresh():
    assert staleness("tags", NOW - timedelta(days=9999), CFG, NOW) == Staleness.fresh
```

- [ ] **Step 2: Run → expect FAIL.**

- [ ] **Step 3: Implement `src/whodex/engine/freshness.py`**

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from whodex.domain.enums import Staleness


class FreshnessConfig(BaseModel):
    ttl_days: dict[str, int] = Field(default_factory=dict)
    grace_factor: float = 2.0


def staleness(field: str, ingested_at: datetime, cfg: FreshnessConfig, now: datetime) -> Staleness:
    ttl = cfg.ttl_days.get(field, 0)
    if ttl == 0:
        return Staleness.fresh
    age = (now - ingested_at).days
    if age < ttl:
        return Staleness.fresh
    return Staleness.stale if age < ttl * cfg.grace_factor else Staleness.expired
```

- [ ] **Step 4: Run → PASS (5 tests). Full gate, commit:**

```bash
git add src/whodex/engine/freshness.py tests/engine/test_freshness.py
git commit -m "feat(engine): per-field staleness classification"
```

---

### Task 5: `engine.reminders` — idempotent reminder generation

**Files:** Create `src/whodex/engine/reminders.py`; Test `tests/engine/test_reminders.py`.

`generate_reminders` takes scored contacts and emits one `Reminder` per contact whose `score.value >= threshold` and is not snoozed (snoozed are already `-inf`). The `fingerprint` is a stable hash of `(entity_id, sorted(reasons))`, so the same situation yields the same fingerprint (anti-spam). IDs come from an injected `IdFactory`.

- [ ] **Step 1: Write `tests/engine/test_reminders.py`**

```python
from datetime import UTC, datetime

from whodex.domain.enums import ReminderReason
from whodex.domain.ids import SequentialIdFactory
from whodex.engine.reminders import generate_reminders
from whodex.engine.scoring import Score, ScoreInput

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _si(eid):
    return ScoreInput(entity_id=eid, display_name=eid, last_interaction_at=None,
                      cadence_days=30, tier="loose")


def test_reminder_generated_above_threshold():
    scored = [(_si("E1"), Score(value=3.0, reasons=["3.0x overdue"]))]
    rems = generate_reminders(scored, ids=SequentialIdFactory("REM"), now=NOW, threshold=1.0)
    assert len(rems) == 1
    assert rems[0].entity_id == "E1"
    assert rems[0].reason == ReminderReason.cadence_lapsed
    assert rems[0].why == ["3.0x overdue"]


def test_below_threshold_and_snoozed_excluded():
    scored = [
        (_si("E1"), Score(value=0.2, reasons=["0.2x overdue"])),       # below threshold
        (_si("E2"), Score(value=float("-inf"), reasons=["snoozed"])),  # snoozed
    ]
    rems = generate_reminders(scored, ids=SequentialIdFactory("REM"), now=NOW, threshold=1.0)
    assert rems == []


def test_fingerprint_is_stable_for_same_situation():
    scored = [(_si("E1"), Score(value=3.0, reasons=["3.0x overdue"]))]
    a = generate_reminders(scored, ids=SequentialIdFactory("REM"), now=NOW, threshold=1.0)[0]
    b = generate_reminders(scored, ids=SequentialIdFactory("REM"), now=NOW, threshold=1.0)[0]
    assert a.fingerprint == b.fingerprint  # same reasons => same fingerprint (id differs)
```

- [ ] **Step 2: Run → expect FAIL.**

- [ ] **Step 3: Implement `src/whodex/engine/reminders.py`**

```python
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime

from whodex.domain.enums import ReminderReason
from whodex.domain.ids import IdFactory
from whodex.domain.state import Reminder
from whodex.engine.scoring import Score, ScoreInput


def _fingerprint(entity_id: str, reasons: list[str]) -> str:
    key = entity_id + "|" + "|".join(sorted(reasons))
    return hashlib.sha256(key.encode()).hexdigest()


def generate_reminders(
    scored: Sequence[tuple[ScoreInput, Score]],
    *,
    ids: IdFactory,
    now: datetime,
    threshold: float,
) -> list[Reminder]:
    """One reminder per contact at/above threshold; deterministic fingerprint per situation."""
    reminders: list[Reminder] = []
    for si, score in scored:
        if score.value < threshold:
            continue
        reminders.append(
            Reminder(
                id=ids.new(), entity_id=si.entity_id, due_at=now,
                reason=ReminderReason.cadence_lapsed,
                fingerprint=_fingerprint(si.entity_id, score.reasons),
                score=score.value, why=list(score.reasons), created_at=now,
            )
        )
    return reminders
```

- [ ] **Step 4: Run → PASS (3 tests). Full gate, commit:**

```bash
git add src/whodex/engine/reminders.py tests/engine/test_reminders.py
git commit -m "feat(engine): idempotent reminder generation with stable fingerprints"
```

---

### Task 6: `engine.queue` + `whodex queue` CLI command

**Files:** Create `src/whodex/engine/queue.py`; Modify `src/whodex/cli/main.py`; Test `tests/engine/test_queue.py`, `tests/cli/test_queue.py`.

- [ ] **Step 1: Write `tests/engine/test_queue.py`**

```python
from datetime import UTC, datetime, timedelta

from tests.conftest import interaction
from whodex.domain.enums import EntityKind, InteractionKind
from whodex.domain.state import EntityState, EventStream
from whodex.engine.queue import priority_queue
from whodex.engine.scoring import ScoringConfig

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _p(eid):
    return EntityState(entity_id=eid, kind=EntityKind.person, display_name=eid)


def test_queue_ranks_overdue_first_and_excludes_snoozed():
    states = {"E1": _p("E1"), "E2": _p("E2")}
    events = EventStream(interactions=[
        interaction(entities=("E2",), kind=InteractionKind.met, occurred=NOW - timedelta(days=5)),
        # E1 never contacted -> max overdue -> ranks above E2 (recently contacted)
    ])
    q = priority_queue(states, events, cfg=ScoringConfig(), now=NOW)
    assert [si.entity_id for si, _ in q][0] == "E1"
    assert all(score.value != float("-inf") for _, score in q)  # snoozed excluded
```

- [ ] **Step 2: Run → expect FAIL.**

- [ ] **Step 3: Implement `src/whodex/engine/queue.py`**

```python
from __future__ import annotations

from datetime import datetime

from whodex.domain.state import EntityGraphState, EventStream
from whodex.engine.scoring import Score, ScoreInput, ScoringConfig, build_score_inputs, score_contact


def priority_queue(
    states: EntityGraphState, events: EventStream, *, cfg: ScoringConfig, now: datetime
) -> list[tuple[ScoreInput, Score]]:
    """Ranked (ScoreInput, Score) pairs, highest first, excluding snoozed (-inf)."""
    scored = [
        (si, score_contact(si, cfg, now))
        for si in build_score_inputs(states, events, cfg=cfg, now=now)
    ]
    live = [(si, sc) for si, sc in scored if sc.value != float("-inf")]
    live.sort(key=lambda pair: pair[1].value, reverse=True)
    return live
```

- [ ] **Step 4: Run → PASS. Then write `tests/cli/test_queue.py`**

```python
from typer.testing import CliRunner

from whodex.cli.main import app

runner = CliRunner()


def test_queue_command_prints_ranked_contacts():
    result = runner.invoke(app, ["queue", "--demo"])
    assert result.exit_code == 0
    assert "Jane Demo" in result.stdout
```

- [ ] **Step 5: Add a `queue` command to `src/whodex/cli/main.py`** (keep the existing `sync`/`version` commands; add imports `from whodex.engine.queue import priority_queue` and `from whodex.engine.scoring import ScoringConfig`)

```python
@app.command()
def queue(demo: bool = typer.Option(False, "--demo", help="run with a built-in demo source")) -> None:
    """Run one sync pass, then print the ranked reach-out queue with why-now."""
    wiring = build_app(demo=demo)
    run_sync(
        wiring.sources, ledger=wiring.ledger, projection=wiring.projection,
        hub=wiring.hub, trust=wiring.trust, now=wiring.clock.now(),
    )
    ranked = priority_queue(
        wiring.projection.load(), wiring.ledger.read_events(),
        cfg=ScoringConfig(), now=wiring.clock.now(),
    )
    if not ranked:
        typer.echo("(no contacts to reach out to)")
        return
    for si, score in ranked:
        typer.echo(f"{score.value:7.2f}  {si.display_name or si.entity_id}  — {'; '.join(score.reasons)}")
```

- [ ] **Step 6: Run `uv run pytest tests/cli/test_queue.py -q` and `uv run whodex queue --demo` (paste output). Full gate, commit:**

```bash
git add src/whodex/engine/queue.py src/whodex/cli/main.py tests/engine/test_queue.py tests/cli/test_queue.py
git commit -m "feat(engine,cli): priority_queue + whodex queue command"
```

---

## Self-review (against DESIGN §8.1–8.3)

- §8.1 prioritization: linear weighted sum, `overdue_ratio` capped, tier multiplier, pin floor, snooze gate, `reasons` for why-now → Tasks 2–3, 6. ✓ (`event_boost` formula present; fed by `open_change_kinds`, exercised by unit tests — real change wiring deferred, noted in Scope.)
- §8.2 freshness: per-field TTL, grace → expired, ttl=0 never stale → Task 4. ✓ (re-check task queue deferred — Scope.)
- §8.3 reminders: threshold + snooze exclusion + stable fingerprint (anti-spam) → Task 5. ✓ (persistence/dispatch deferred — Scope.)
- Purity: every function takes `now` (and ids) as parameters; `engine` imports only `whodex.domain`. ✓
- Placeholders: none — complete code in every step.
- Type consistency: `ScoreInput`/`Score`/`ScoringConfig`/`build_score_inputs`/`score_contact`/`staleness`/`generate_reminders`/`priority_queue` signatures are identical across tasks and the CLI.
