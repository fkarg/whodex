"""Edge projection: resolve wikilink-valued observations into Edges,
and emit GraphRepairSuggestions for unresolved/placeholder refs.

This module is PURE domain — no store imports, no IO.
`build_edges` accepts a `resolve` callable so the caller supplies store logic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from datetime import datetime

from whodex.domain.enums import EdgeType
from whodex.domain.events import Observation
from whodex.domain.ids import IdFactory
from whodex.domain.refs import EntityRef
from whodex.domain.state import Edge, GraphRepairSuggestion

# Maps "entity_kind.field_name" → EdgeType
EDGE_FOR: dict[str, EdgeType] = {
    "person.organisations": EdgeType.member_of,
    "person.lives": EdgeType.lives_in,
    "org.location": EdgeType.located_in,
    "org.parent": EdgeType.part_of,
    "event.location": EdgeType.hosted_at,
    "event.organizer": EdgeType.organized_by,
    "event.participants": EdgeType.attended,
}


def _fingerprint_unresolved(src: str, field: str, target: str) -> str:
    key = f"unresolved|{src}|{field}|{target}"
    return hashlib.sha256(key.encode()).hexdigest()


def _fingerprint_placeholder(src: str, field: str, raw: str) -> str:
    key = f"placeholder|{src}|{field}|{raw}"
    return hashlib.sha256(key.encode()).hexdigest()


def build_edges(
    observations: Iterable[Observation],
    *,
    resolve: Callable[[EntityRef], str | None],
    ids: IdFactory,
    now: datetime,
) -> tuple[list[Edge], list[GraphRepairSuggestion]]:
    """Project wikilink-valued observations into Edges and repair suggestions.

    Parameters
    ----------
    observations:
        All observations to consider. Only those whose field is in EDGE_FOR
        and which have an entity_id are processed.
    resolve:
        Callable that maps an EntityRef to a resolved entity_id, or None if
        the ref cannot be resolved. Must NOT be called for refs without a
        target_path (placeholders).
    ids:
        IdFactory used to generate IDs for new Edges and GraphRepairSuggestions.
    now:
        Timestamp used for detected_at on repair suggestions.
    """
    # Dedup sets
    seen_edges: set[tuple[str, str, str]] = set()  # (src, dst, type)
    seen_repairs: set[str] = set()  # fingerprints

    edges: list[Edge] = []
    repairs: list[GraphRepairSuggestion] = []

    for obs in observations:
        if obs.entity_id is None:
            continue
        field = obs.field
        if field not in EDGE_FOR:
            continue

        edge_type = EDGE_FOR[field]
        src = obs.entity_id

        # Normalise value to a list of strings for uniform processing
        raw_values: list[str]
        if isinstance(obs.value, list):
            raw_values = [str(v) for v in obs.value]
        else:
            raw_values = [str(obs.value)]

        for raw_val in raw_values:
            ref = EntityRef.parse(raw_val)

            if ref.target_path is not None:
                # Wikilink — try to resolve
                resolved_id = resolve(ref)
                if resolved_id is not None:
                    key = (src, resolved_id, edge_type.value)
                    if key not in seen_edges:
                        seen_edges.add(key)
                        edges.append(
                            Edge(
                                id=ids.new(),
                                src_entity_id=src,
                                dst_entity_id=resolved_id,
                                type=edge_type,
                                observed_at=obs.observed_at,
                            )
                        )
                else:
                    # Unresolved wikilink
                    fp = _fingerprint_unresolved(src, field, ref.target_path)
                    if fp not in seen_repairs:
                        seen_repairs.add(fp)
                        repairs.append(
                            GraphRepairSuggestion(
                                id=ids.new(),
                                repair_type="unresolved_ref",
                                src_entity_id=src,
                                payload={
                                    "field": field,
                                    "target": ref.target_path,
                                    "raw": ref.raw,
                                },
                                fingerprint=fp,
                                detected_at=now,
                            )
                        )
            else:
                # Bare scalar placeholder — no target_path
                fp = _fingerprint_placeholder(src, field, ref.raw)
                if fp not in seen_repairs:
                    seen_repairs.add(fp)
                    repairs.append(
                        GraphRepairSuggestion(
                            id=ids.new(),
                            repair_type="placeholder_ref",
                            src_entity_id=src,
                            payload={
                                "field": field,
                                "raw": ref.raw,
                            },
                            fingerprint=fp,
                            detected_at=now,
                        )
                    )

    return edges, repairs
