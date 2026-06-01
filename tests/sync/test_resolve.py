"""Tests for make_resolver: resolves EntityRef to entity_id via InMemoryEntityStore."""

from __future__ import annotations

from datetime import UTC, datetime

from whodex.domain.enums import EntityKind
from whodex.domain.ids import SequentialIdFactory
from whodex.domain.refs import EntityRef
from whodex.store.memory import InMemoryEntityStore
from whodex.sync.resolve import make_resolver

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _store() -> tuple[InMemoryEntityStore, SequentialIdFactory]:
    ids = SequentialIdFactory("ENT")
    store = InMemoryEntityStore(ids)
    return store, ids


# ---------------------------------------------------------------------------
# Core: vault_path match with .md suffix
# ---------------------------------------------------------------------------


def test_make_resolver_resolves_wikilink_by_vault_path_with_md():
    store, ids = _store()
    eid = store.create_entity(EntityKind.organisation, created_at=NOW)
    store.add_identifiers(eid, [("vault_path", "Organisations/Kolai.md")])
    resolve = make_resolver(store)

    result = resolve(EntityRef.parse("[[Organisations/Kolai]]"))

    assert result == eid


def test_make_resolver_resolves_wikilink_by_vault_path_without_md():
    """Fallback: vault_path stored without .md extension."""
    store, ids = _store()
    eid = store.create_entity(EntityKind.organisation, created_at=NOW)
    store.add_identifiers(eid, [("vault_path", "Organisations/Kolai")])
    resolve = make_resolver(store)

    result = resolve(EntityRef.parse("[[Organisations/Kolai]]"))

    assert result == eid


def test_make_resolver_returns_none_for_unknown_wikilink():
    store, ids = _store()
    resolve = make_resolver(store)

    result = resolve(EntityRef.parse("[[Organisations/Nobody]]"))

    assert result is None


def test_make_resolver_returns_none_for_bare_scalar():
    """Bare scalars (no target_path) always return None."""
    store, ids = _store()
    resolve = make_resolver(store)

    result = resolve(EntityRef.parse("Unknown"))

    assert result is None


# ---------------------------------------------------------------------------
# Integration: make_resolver + build_edges resolve a ref end-to-end
# ---------------------------------------------------------------------------


def test_make_resolver_integrates_with_build_edges():

    from tests.conftest import obs as make_obs
    from whodex.domain.ids import SequentialIdFactory
    from whodex.projection.edges import build_edges

    store, ids = _store()
    org_id = store.create_entity(EntityKind.organisation, created_at=NOW)
    store.add_identifiers(org_id, [("vault_path", "Organisations/Kolai.md")])

    person_id = "PERSON-001"
    observation = make_obs(
        entity=person_id,
        field="person.organisations",
        value="[[Organisations/Kolai]]",
    )

    resolve = make_resolver(store)
    edges, repairs = build_edges(
        [observation],
        resolve=resolve,
        ids=SequentialIdFactory("EDGE"),
        now=NOW,
    )

    assert len(edges) == 1
    assert edges[0].src_entity_id == person_id
    assert edges[0].dst_entity_id == org_id
    assert len(repairs) == 0
