"""Phase-1c end-to-end acceptance invariants.

These tests exercise the full durable graph pipeline (edges, repair
suggestions, who-at queries) over the self-contained ``fixtures/people-network-min/``
vault.  They encode the *acceptance criteria* for Phase 1c and must never be
weakened: a failing invariant means a real defect.

Invariants
----------
G1  After sync the expected edges exist (Ada→Acme member_of, Ada→Berlin
    lives_in, Bo→Acme member_of, Bo→OpenNet member_of, Bo→Hamburg lives_in);
    a second sync over the same vault+db yields the SAME edge set (idempotent).

G2  A People note whose ``organisations`` list contains an unresolvable
    wikilink produces exactly one ``unresolved_ref`` GraphRepairSuggestion;
    a second sync keeps it at exactly one (stable fingerprint, no growth).

G5  ``people_at(app.edges, acme_id)`` returns Ada's entity id; Acme is
    resolved via ``app.entities.find_by_identifiers([("vault_path", "Organisations/Acme.md")])``.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whodex.config.settings import build_app
from whodex.domain.enums import EdgeType
from whodex.engine.graph import people_at
from whodex.sync.engine import run_sync

# ---------------------------------------------------------------------------
# Fixture paths & helpers
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent.parent / "fixtures" / "people-network-min"
NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _copy_vault(tmp_path: Path) -> Path:
    """Copy the fixture vault into tmp_path so writes stay isolated."""
    dest = tmp_path / "vault"
    shutil.copytree(FIXTURE, dest)
    return dest


def _run_sync(vault: Path, db: Path) -> object:
    """Build a fresh App over (vault, db) and run a full graph sync; return (app, report)."""
    app = build_app(vault=vault, db=db)
    report = run_sync(
        app.sources,
        ledger=app.ledger,
        projection=app.projection,
        hub=app.hub,
        trust=app.trust,
        now=NOW,
        entities=app.entities,
        edge_store=app.edges,
        derived_store=app.derived,
    )
    return app, report


# ---------------------------------------------------------------------------
# Invariant G1 — expected edges exist and are idempotent across two syncs
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_g1_expected_edges_exist_after_sync(tmp_path: Path) -> None:
    """G1a: After the first sync the 5 fixture edges must be present.

    Ada → Acme (member_of), Ada → Berlin (lives_in),
    Bo  → Acme (member_of), Bo  → OpenNet (member_of), Bo → Hamburg (lives_in).
    """
    vault, db = _copy_vault(tmp_path), tmp_path / "whodex.db"
    app, _ = _run_sync(vault, db)

    # Resolve entity ids from vault_path identifiers
    ada_id = app.entities.find_by_identifiers([("vault_path", "People/Ada Engineer.md")])
    acme_id = app.entities.find_by_identifiers([("vault_path", "Organisations/Acme.md")])
    opennet_id = app.entities.find_by_identifiers([("vault_path", "Organisations/OpenNet.md")])
    berlin_id = app.entities.find_by_identifiers([("vault_path", "Locations/Berlin.md")])
    bo_id = app.entities.find_by_identifiers([("vault_path", "People/Bo Founder.md")])
    hamburg_id = app.entities.find_by_identifiers([("vault_path", "Locations/Hamburg.md")])

    assert ada_id is not None, "Ada entity not found — vault_path identifier missing"
    assert acme_id is not None, "Acme entity not found"
    assert opennet_id is not None, "OpenNet entity not found"
    assert berlin_id is not None, "Berlin entity not found"
    assert bo_id is not None, "Bo entity not found"
    assert hamburg_id is not None, "Hamburg entity not found"

    # Build (src, dst, type) key set for fast membership checks
    edge_keys = {(e.src_entity_id, e.dst_entity_id, e.type) for e in app.edges.all_edges()}

    assert (ada_id, acme_id, EdgeType.member_of) in edge_keys, (
        "Expected Ada → Acme member_of edge is missing"
    )
    assert (ada_id, berlin_id, EdgeType.lives_in) in edge_keys, (
        "Expected Ada → Berlin lives_in edge is missing"
    )
    assert (bo_id, acme_id, EdgeType.member_of) in edge_keys, (
        "Expected Bo → Acme member_of edge is missing"
    )
    assert (bo_id, opennet_id, EdgeType.member_of) in edge_keys, (
        "Expected Bo → OpenNet member_of edge is missing"
    )
    assert (bo_id, hamburg_id, EdgeType.lives_in) in edge_keys, (
        "Expected Bo → Hamburg lives_in edge is missing"
    )


@pytest.mark.e2e
def test_g1_edge_set_is_idempotent_across_two_syncs(tmp_path: Path) -> None:
    """G1b: A second sync must produce the exact same edge set — no duplicates, no drift.

    ``all_edges()`` count must be identical and every (src, dst, type) tuple
    present after the first sync must still be present after the second.
    """
    vault, db = _copy_vault(tmp_path), tmp_path / "whodex.db"

    app1, _ = _run_sync(vault, db)
    edges_after_first = {(e.src_entity_id, e.dst_entity_id, e.type) for e in app1.edges.all_edges()}
    count_after_first = len(app1.edges.all_edges())

    app2, _ = _run_sync(vault, db)
    edges_after_second = {
        (e.src_entity_id, e.dst_entity_id, e.type) for e in app2.edges.all_edges()
    }
    count_after_second = len(app2.edges.all_edges())

    assert count_after_second == count_after_first, (
        f"Edge count changed after second sync: {count_after_first} → {count_after_second}. "
        "Edges may be duplicated or dropped."
    )
    assert edges_after_second == edges_after_first, (
        f"Edge set changed after second sync.\n"
        f"  Added: {edges_after_second - edges_after_first!r}\n"
        f"  Removed: {edges_after_first - edges_after_second!r}"
    )


# ---------------------------------------------------------------------------
# Invariant G2 — unresolved_ref repair dedup: exactly one suggestion, stable
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_g2_unresolved_ref_produces_exactly_one_repair(tmp_path: Path) -> None:
    """G2a: A note with an unresolvable wikilink produces exactly one unresolved_ref repair."""
    vault, db = _copy_vault(tmp_path), tmp_path / "whodex.db"

    # Add a People note with a wikilink to a non-existent org
    ghost_note = vault / "People" / "Ghost User.md"
    ghost_note.write_text(
        "---\n"
        "type: Person\n"
        "organisations:\n"
        '  - "[[Organisations/DoesNotExist]]"\n'
        "tags:\n"
        "  - Person\n"
        "---\n\n"
        "## Notes\n"
        "- Intentionally broken wikilink for repair invariant G2.\n"
    )

    app, report = _run_sync(vault, db)

    repairs = app.derived.repairs()
    unresolved = [r for r in repairs if r.repair_type == "unresolved_ref"]

    assert len(unresolved) == 1, (
        f"Expected exactly 1 unresolved_ref repair, got {len(unresolved)}. "
        f"All repairs: {[(r.repair_type, r.payload) for r in repairs]!r}"
    )
    assert unresolved[0].payload.get("target") == "Organisations/DoesNotExist", (
        f"Unexpected repair target: {unresolved[0].payload!r}"
    )
    assert report.repairs == 1, f"SyncReport.repairs expected 1, got {report.repairs}"


@pytest.mark.e2e
def test_g2_unresolved_ref_repair_is_stable_on_second_sync(tmp_path: Path) -> None:
    """G2b: A second sync must not grow the repair set.

    Fingerprint dedup keeps it at exactly one.
    """
    vault, db = _copy_vault(tmp_path), tmp_path / "whodex.db"

    ghost_note = vault / "People" / "Ghost User.md"
    ghost_note.write_text(
        "---\n"
        "type: Person\n"
        "organisations:\n"
        '  - "[[Organisations/DoesNotExist]]"\n'
        "tags:\n"
        "  - Person\n"
        "---\n"
    )

    app1, _ = _run_sync(vault, db)
    fp_after_first = {r.fingerprint for r in app1.derived.repairs()}
    count_after_first = len(app1.derived.repairs())

    app2, _ = _run_sync(vault, db)
    fp_after_second = {r.fingerprint for r in app2.derived.repairs()}
    count_after_second = len(app2.derived.repairs())

    assert count_after_second == count_after_first, (
        f"Repair count changed after second sync: {count_after_first} → {count_after_second}. "
        "Fingerprint dedup is broken — repairs are growing."
    )
    assert fp_after_second == fp_after_first, (
        f"Repair fingerprints changed after second sync.\n"
        f"  Added: {fp_after_second - fp_after_first!r}\n"
        f"  Removed: {fp_after_first - fp_after_second!r}"
    )


# ---------------------------------------------------------------------------
# Invariant G5 — who-at: people_at(edges, acme_id) returns Ada's entity id
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_g5_people_at_acme_includes_ada(tmp_path: Path) -> None:
    """G5: people_at(edges, acme_id) must return Ada's entity id after a full sync.

    Acme is resolved via find_by_identifiers(vault_path=Organisations/Acme.md).
    """
    vault, db = _copy_vault(tmp_path), tmp_path / "whodex.db"
    app, _ = _run_sync(vault, db)

    acme_id = app.entities.find_by_identifiers([("vault_path", "Organisations/Acme.md")])
    ada_id = app.entities.find_by_identifiers([("vault_path", "People/Ada Engineer.md")])

    assert acme_id is not None, "Acme entity not found via vault_path identifier"
    assert ada_id is not None, "Ada entity not found via vault_path identifier"

    person_ids_at_acme = people_at(app.edges, acme_id)

    assert ada_id in person_ids_at_acme, (
        f"Ada ({ada_id}) not found at Acme ({acme_id}). people_at returned: {person_ids_at_acme!r}"
    )


@pytest.mark.e2e
def test_g5_people_at_berlin_includes_ada(tmp_path: Path) -> None:
    """G5b: people_at(edges, berlin_id) must return Ada's entity id (lives_in edge)."""
    vault, db = _copy_vault(tmp_path), tmp_path / "whodex.db"
    app, _ = _run_sync(vault, db)

    berlin_id = app.entities.find_by_identifiers([("vault_path", "Locations/Berlin.md")])
    ada_id = app.entities.find_by_identifiers([("vault_path", "People/Ada Engineer.md")])

    assert berlin_id is not None, "Berlin entity not found"
    assert ada_id is not None, "Ada entity not found"

    person_ids_at_berlin = people_at(app.edges, berlin_id)

    assert ada_id in person_ids_at_berlin, (
        f"Ada ({ada_id}) not found at Berlin ({berlin_id}). "
        f"people_at returned: {person_ids_at_berlin!r}"
    )
