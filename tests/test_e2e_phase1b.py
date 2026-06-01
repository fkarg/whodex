"""Phase-1b end-to-end acceptance invariants.

These tests exercise the full durable pipeline (ObsidianSource → SQLite
ledger + JSONL mirror + entity store + projection) over a self-contained,
anonymised vault fixture.  They encode the *acceptance criteria* for Phase 1b
and must never be weakened: a failing invariant means a real defect.

Invariants
----------
I1  Re-sync over an existing durable DB produces zero new entities and zero
    changes; person entity count == number of People/*.md notes.
I2  Entity IDs are stable across independent builds over the same DB.
I3  Replaying the SQLite ledger and the JSONL mirror through `project()`
    yields identical state maps.
I4  Smoke: the fixture is fully parseable and yields a deterministic,
    identical person-entity count across two independent fresh DBs.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whodex.config.settings import build_app
from whodex.domain.enums import EntityKind
from whodex.projection.project import project
from whodex.store.jsonl import read_events_from_jsonl
from whodex.sync.engine import run_sync

# ---------------------------------------------------------------------------
# Fixture paths & helpers
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent.parent / "fixtures" / "people-network-min"
NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _copy_vault(tmp_path: Path) -> Path:
    """Copy the fixture vault into tmp_path so JSONL and DB writes stay isolated."""
    dest = tmp_path / "vault"
    shutil.copytree(FIXTURE, dest)
    return dest


def _sync(vault: Path, db: Path) -> object:
    """Build a fresh App over (vault, db) and run a full sync; return the report."""
    app = build_app(vault=vault, db=db)
    return run_sync(
        app.sources,
        ledger=app.ledger,
        projection=app.projection,
        hub=app.hub,
        trust=app.trust,
        now=NOW,
    )


def _person_note_count(vault: Path) -> int:
    """Number of .md files under People/ in the vault."""
    return len(list((vault / "People").glob("*.md")))


def _person_entity_count(vault: Path, db: Path) -> int:
    """Number of entities with kind=person in the durable entity store."""
    app = build_app(vault=vault, db=db)
    return sum(1 for kind in app.hub.identity.kinds.values() if kind == EntityKind.person)


# ---------------------------------------------------------------------------
# Invariant I1 — re-sync is idempotent: no duplicate entities, zero changes
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_resync_is_idempotent_no_dup_entities_and_zero_changes(tmp_path: Path) -> None:
    """I1: A second sync over the same durable DB must be a no-op.

    Person entity count must equal the number of People/*.md notes (no
    duplicates), and the SyncReport must report zero changes.
    """
    vault, db = _copy_vault(tmp_path), tmp_path / "whodex.db"

    _sync(vault, db)  # first sync — populate the DB
    r2 = _sync(vault, db)  # second sync — must be idempotent

    persons = _person_entity_count(vault, db)
    person_notes = _person_note_count(vault)
    assert persons == person_notes, (
        f"Expected {person_notes} person entities (one per People note), got {persons}. "
        "Duplicate entities were created on re-sync."
    )
    assert r2.changes == 0, (
        f"Second sync reported {r2.changes} changes on an unchanged vault — not idempotent."
    )


# ---------------------------------------------------------------------------
# Invariant I2 — entity IDs are stable across independent App instances
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_identity_stable_across_separate_runs(tmp_path: Path) -> None:
    """I2: The same durable DB must resolve to the same entity IDs in any App build.

    Builds a fresh App (without sharing any state) after each sync and checks
    that the entity-ID set is identical.
    """
    vault, db = _copy_vault(tmp_path), tmp_path / "whodex.db"

    _sync(vault, db)
    kinds1 = dict(build_app(vault=vault, db=db).hub.identity.kinds)

    _sync(vault, db)
    kinds2 = dict(build_app(vault=vault, db=db).hub.identity.kinds)

    assert set(kinds1) == set(kinds2), (
        "Entity IDs changed between builds over the same DB. "
        f"Added: {set(kinds2) - set(kinds1)!r}, "
        f"removed: {set(kinds1) - set(kinds2)!r}"
    )
    # Also check kinds are unchanged (no kind reassignment)
    assert kinds1 == kinds2, (
        "Entity kinds changed between builds over the same DB."
    )


# ---------------------------------------------------------------------------
# Invariant I3 — JSONL mirror and SQLite ledger project to identical state
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_state_rebuilds_identically_from_ledger_and_jsonl(tmp_path: Path) -> None:
    """I3: Replaying SQLite events and JSONL events through project() is equivalent.

    The JSONL mirror is an append-only backup.  Projecting it must yield the
    same entity state map as projecting the SQLite ledger.
    """
    vault, db = _copy_vault(tmp_path), tmp_path / "whodex.db"
    _sync(vault, db)

    app = build_app(vault=vault, db=db)
    events_sqlite = app.ledger.read_events()
    events_jsonl = read_events_from_jsonl(vault / ".whodex" / "events")

    kinds = app.hub.identity.kinds
    s_sql = project(events_sqlite, None, trust=app.trust, kinds=kinds, now=NOW).states
    s_jsonl = project(events_jsonl, None, trust=app.trust, kinds=kinds, now=NOW).states

    assert set(s_sql) == set(s_jsonl), (
        f"SQLite and JSONL entity sets differ. "
        f"Only in SQLite: {set(s_sql) - set(s_jsonl)!r}, "
        f"only in JSONL: {set(s_jsonl) - set(s_sql)!r}"
    )
    for eid in s_sql:
        sql_fields = s_sql[eid].fields
        jsonl_fields = s_jsonl[eid].fields
        assert sql_fields == jsonl_fields, (
            f"Entity {eid}: SQLite fields != JSONL fields.\n"
            f"  SQLite: {sql_fields!r}\n"
            f"  JSONL:  {jsonl_fields!r}"
        )


# ---------------------------------------------------------------------------
# Invariant I4 — smoke: fixture parses deterministically on two fresh DBs
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_smoke_fixture_parses_all_people_deterministically(tmp_path: Path) -> None:
    """I4: Two independent fresh syncs over the same vault produce identical entity counts.

    Observations ingested must be > 0 (the vault is non-empty), and person
    entity count must be consistent and equal to the People-note count.
    """
    vault = _copy_vault(tmp_path)
    db1 = tmp_path / "w1.db"
    db2 = tmp_path / "w2.db"

    r1 = _sync(vault, db1)
    assert r1.observations_ingested > 0, (
        "First sync produced no observations — the fixture vault may not have been read."
    )

    _sync(vault, db2)

    pc1 = _person_entity_count(vault, db1)
    pc2 = _person_entity_count(vault, db2)
    expected = _person_note_count(vault)

    assert pc1 == expected, (
        f"DB1 person entity count ({pc1}) != People note count ({expected})."
    )
    assert pc2 == expected, (
        f"DB2 person entity count ({pc2}) != People note count ({expected})."
    )
    assert pc1 == pc2, (
        f"Two fresh DBs yielded different person entity counts: {pc1} vs {pc2}."
    )
