"""Behavioral tests for engine.graph contact-point helpers (G5)."""

from __future__ import annotations

from datetime import UTC, datetime

from whodex.domain.enums import EdgeType
from whodex.domain.state import Edge
from whodex.engine.graph import contact_points, people_at
from whodex.store.memory import InMemoryEdgeStore

_T = datetime(2026, 1, 1, tzinfo=UTC)
_COUNTER = {"n": 0}


def _eid(prefix: str = "e") -> str:
    _COUNTER["n"] += 1
    return f"{prefix}-{_COUNTER['n']:04d}"


def _edge(src: str, dst: str, etype: EdgeType) -> Edge:
    return Edge(
        id=_eid("edge"),
        src_entity_id=src,
        dst_entity_id=dst,
        type=etype,
        observed_at=_T,
    )


def test_people_at_org_returns_members() -> None:
    person1 = "person-001"
    person2 = "person-002"
    org = "org-001"

    store = InMemoryEdgeStore()
    store.replace_edges(
        [
            _edge(person1, org, EdgeType.member_of),
            _edge(person2, org, EdgeType.member_of),
        ]
    )

    result = people_at(store, org)
    assert set(result) == {person1, person2}


def test_people_at_location_returns_residents() -> None:
    person1 = "person-001"
    loc = "loc-001"

    store = InMemoryEdgeStore()
    store.replace_edges([_edge(person1, loc, EdgeType.lives_in)])

    result = people_at(store, loc)
    assert result == [person1]


def test_people_at_org_excludes_other_nodes() -> None:
    person1 = "person-001"
    person2 = "person-002"
    org = "org-001"
    loc = "loc-001"

    store = InMemoryEdgeStore()
    store.replace_edges(
        [
            _edge(person1, org, EdgeType.member_of),
            _edge(person1, loc, EdgeType.lives_in),
        ]
    )

    # org only contains person1
    assert people_at(store, org) == [person1]
    # loc only contains person1 too, but via lives_in
    assert people_at(store, loc) == [person1]
    # person2 is not at org
    assert person2 not in people_at(store, org)


def test_people_at_org_and_location_combined() -> None:
    """people_at merges both member_of and lives_in edges."""
    person1 = "person-001"
    person2 = "person-002"
    org = "org-001"
    loc = "loc-001"

    store = InMemoryEdgeStore()
    store.replace_edges(
        [
            _edge(person1, org, EdgeType.member_of),
            _edge(person2, org, EdgeType.member_of),
            _edge(person1, loc, EdgeType.lives_in),
        ]
    )

    # org: person1 + person2 via member_of
    assert set(people_at(store, org)) == {person1, person2}
    # loc: person1 via lives_in
    assert people_at(store, loc) == [person1]


def test_contact_points_includes_org_and_location() -> None:
    person1 = "person-001"
    org = "org-001"
    loc = "loc-001"

    store = InMemoryEdgeStore()
    store.replace_edges(
        [
            _edge(person1, org, EdgeType.member_of),
            _edge(person1, loc, EdgeType.lives_in),
        ]
    )

    cps = contact_points(store, person1)
    assert org in cps
    assert loc in cps


def test_contact_points_includes_attended_events() -> None:
    person1 = "person-001"
    event1 = "event-001"

    store = InMemoryEdgeStore()
    store.replace_edges([_edge(person1, event1, EdgeType.attended)])

    cps = contact_points(store, person1)
    assert event1 in cps


def test_contact_points_empty_for_unconnected_person() -> None:
    store = InMemoryEdgeStore()
    store.replace_edges([])

    assert contact_points(store, "lone-wolf") == []


def test_people_at_empty_returns_empty() -> None:
    store = InMemoryEdgeStore()
    store.replace_edges([])

    assert people_at(store, "org-nobody") == []
