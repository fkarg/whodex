"""Contact-point query helpers (G5 invariant).

These are pure-ish helpers: they receive stores as parameters and contain no
import of concrete store implementations.  ``engine`` may import ``domain``
and use the store Protocol types for type annotations only.
"""

from __future__ import annotations

from whodex.domain.enums import EdgeType
from whodex.store.interfaces import EdgeStore


def people_at(edges: EdgeStore, org_or_location_id: str) -> list[str]:
    """Return entity ids of people who are *at* the given org or location.

    Concretely: src_entity_ids of INCOMING ``member_of`` (org) **or**
    ``lives_in`` (location) edges that terminate at *org_or_location_id*.
    """
    incoming_member = edges.incoming(org_or_location_id, EdgeType.member_of)
    incoming_lives = edges.incoming(org_or_location_id, EdgeType.lives_in)
    return [e.src_entity_id for e in incoming_member + incoming_lives]


def contact_points(edges: EdgeStore, person_id: str) -> list[str]:
    """Return dst_entity_ids of a person's outgoing membership/location/event edges.

    Covers ``member_of``, ``lives_in``, and ``attended`` edge types.
    """
    result: list[str] = []
    for etype in (EdgeType.member_of, EdgeType.lives_in, EdgeType.attended):
        result.extend(e.dst_entity_id for e in edges.outgoing(person_id, etype))
    return result
