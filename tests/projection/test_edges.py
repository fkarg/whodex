"""Behavioral tests for edge projection (build_edges).

Tests are parametric over EDGE_FOR and cover:
- Per-field: single wikilink → correct Edge type, src/dst
- MULTI_REF (person.organisations) → multiple edges
- Unresolved wikilink → GraphRepairSuggestion(unresolved_ref), deduplicated
- Placeholder scalar → GraphRepairSuggestion(placeholder_ref)
- Non-edge fields → no output
- Fingerprint stability across calls
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.conftest import obs
from whodex.domain.enums import EdgeType
from whodex.domain.ids import SequentialIdFactory
from whodex.projection.edges import EDGE_FOR, build_edges

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _ids():
    return SequentialIdFactory("E")


def _resolve_from(mapping: dict[str, str]):
    """Return a resolve callable backed by a dict: target_path -> entity_id."""
    from whodex.domain.refs import EntityRef

    def resolve(ref: EntityRef) -> str | None:
        if ref.target_path is None:
            return None
        return mapping.get(ref.target_path)

    return resolve


# ---------------------------------------------------------------------------
# Parametric: each field in EDGE_FOR with a resolvable wikilink → one Edge
# ---------------------------------------------------------------------------

_SAMPLE_ENTITY = "ENT-001"
_DST_ENTITY = "ENT-002"

_FIELD_VALUES: dict[str, str | list[str]] = {
    "person.organisations": "[[Organisations/Kolai]]",
    "person.lives": "[[Locations/Berlin]]",
    "org.location": "[[Locations/Berlin]]",
    "org.parent": "[[Organisations/ParentCo]]",
    "event.location": "[[Locations/Conference]]",
    "event.organizer": "[[People/Alice]]",
    "event.participants": "[[People/Bob]]",
}


@pytest.mark.parametrize("field,edge_type", list(EDGE_FOR.items()))
def test_resolvable_wikilink_produces_edge_of_correct_type(field: str, edge_type: EdgeType):
    raw_value = _FIELD_VALUES[field]
    observation = obs(entity=_SAMPLE_ENTITY, field=field, value=raw_value)
    target = raw_value.strip("[]").split("|")[0]  # e.g. "Organisations/Kolai"
    resolve = _resolve_from({target: _DST_ENTITY})

    edges, repairs = build_edges([observation], resolve=resolve, ids=_ids(), now=NOW)

    assert len(edges) == 1, f"Expected 1 edge for field {field!r}"
    assert edges[0].type == edge_type
    assert edges[0].src_entity_id == _SAMPLE_ENTITY
    assert edges[0].dst_entity_id == _DST_ENTITY
    assert len(repairs) == 0


@pytest.mark.parametrize("field,edge_type", list(EDGE_FOR.items()))
def test_edge_observed_at_matches_observation(field: str, edge_type: EdgeType):
    obs_time = datetime(2026, 3, 15, tzinfo=UTC)
    raw_value = _FIELD_VALUES[field]
    observation = obs(entity=_SAMPLE_ENTITY, field=field, value=raw_value, observed=obs_time)
    target = raw_value.strip("[]").split("|")[0]
    resolve = _resolve_from({target: _DST_ENTITY})

    edges, _ = build_edges([observation], resolve=resolve, ids=_ids(), now=NOW)

    assert edges[0].observed_at == obs_time


# ---------------------------------------------------------------------------
# MULTI_REF: person.organisations with 2 wikilinks → 2 edges
# ---------------------------------------------------------------------------


def test_multi_ref_list_produces_multiple_edges():
    DST_A, DST_B = "ENT-A", "ENT-B"
    value = ["[[Organisations/Kolai]]", "[[Organisations/Acme]]"]
    observation = obs(entity=_SAMPLE_ENTITY, field="person.organisations", value=value)
    resolve = _resolve_from(
        {
            "Organisations/Kolai": DST_A,
            "Organisations/Acme": DST_B,
        }
    )

    edges, repairs = build_edges([observation], resolve=resolve, ids=_ids(), now=NOW)

    assert len(edges) == 2
    assert len(repairs) == 0
    dst_ids = {e.dst_entity_id for e in edges}
    assert dst_ids == {DST_A, DST_B}
    assert all(e.type == EdgeType.member_of for e in edges)
    assert all(e.src_entity_id == _SAMPLE_ENTITY for e in edges)


# ---------------------------------------------------------------------------
# Unresolved wikilink → suggestion, no edge; same target twice → ONE suggestion
# ---------------------------------------------------------------------------


def test_unresolved_wikilink_produces_repair_suggestion():
    observation = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="[[Locations/Unknown]]")
    resolve = _resolve_from({})  # nothing resolves

    edges, repairs = build_edges([observation], resolve=resolve, ids=_ids(), now=NOW)

    assert len(edges) == 0
    assert len(repairs) == 1
    r = repairs[0]
    assert r.repair_type == "unresolved_ref"
    assert r.src_entity_id == _SAMPLE_ENTITY
    assert r.payload["field"] == "person.lives"
    assert r.payload["target"] == "Locations/Unknown"


def test_same_unresolved_target_twice_collapsed_to_one_suggestion():
    """Two observations for the same (src, field, target) → exactly one suggestion."""
    obs1 = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="[[Locations/Unknown]]")
    obs2 = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="[[Locations/Unknown]]")
    resolve = _resolve_from({})

    edges, repairs = build_edges([obs1, obs2], resolve=resolve, ids=_ids(), now=NOW)

    assert len(edges) == 0
    assert len(repairs) == 1


# ---------------------------------------------------------------------------
# Placeholder scalar (no target_path) → placeholder_ref suggestion
# ---------------------------------------------------------------------------


def test_placeholder_scalar_produces_placeholder_ref_suggestion():
    observation = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="Unknown")
    resolve = _resolve_from({})  # irrelevant — no target_path

    edges, repairs = build_edges([observation], resolve=resolve, ids=_ids(), now=NOW)

    assert len(edges) == 0
    assert len(repairs) == 1
    r = repairs[0]
    assert r.repair_type == "placeholder_ref"
    assert r.src_entity_id == _SAMPLE_ENTITY
    assert r.payload["field"] == "person.lives"
    assert r.payload["raw"] == "Unknown"


# ---------------------------------------------------------------------------
# Non-edge fields → no edges, no suggestions
# ---------------------------------------------------------------------------


def test_non_edge_field_produces_no_output():
    observation = obs(entity=_SAMPLE_ENTITY, field="job.title", value="Engineer")

    edges, repairs = build_edges([observation], resolve=_resolve_from({}), ids=_ids(), now=NOW)

    assert edges == []
    assert repairs == []


def test_scalar_field_produces_no_output():
    observation = obs(entity=_SAMPLE_ENTITY, field="name.full", value="Alice")

    edges, repairs = build_edges([observation], resolve=_resolve_from({}), ids=_ids(), now=NOW)

    assert edges == []
    assert repairs == []


# ---------------------------------------------------------------------------
# Observations without entity_id are skipped
# ---------------------------------------------------------------------------


def test_observation_without_entity_id_is_skipped():
    from whodex.domain.canonical import value_hash
    from whodex.domain.enums import ObsOp
    from whodex.domain.events import Observation

    NOW_T = datetime(2026, 1, 1, tzinfo=UTC)
    observation = Observation(
        id="OBS-anon",
        source_run_id="RUN-X",
        source_kind="fake",
        entity_id=None,  # no entity
        external_ref="anon",
        external_ref_kind="fake_id",
        field="person.lives",
        op=ObsOp.set,
        value="[[Locations/Berlin]]",
        value_hash=value_hash("person.lives", ObsOp.set, "[[Locations/Berlin]]"),
        observed_at=NOW_T,
        ingested_at=NOW_T,
    )
    resolve = _resolve_from({"Locations/Berlin": "ENT-99"})

    edges, repairs = build_edges([observation], resolve=resolve, ids=_ids(), now=NOW)

    assert edges == []
    assert repairs == []


# ---------------------------------------------------------------------------
# Edge deduplication: same (src, dst, type) from two observations → one edge
# ---------------------------------------------------------------------------


def test_duplicate_edge_by_src_dst_type_is_deduplicated():
    obs1 = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="[[Locations/Berlin]]")
    obs2 = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="[[Locations/Berlin]]")
    resolve = _resolve_from({"Locations/Berlin": _DST_ENTITY})

    edges, _ = build_edges([obs1, obs2], resolve=resolve, ids=_ids(), now=NOW)

    assert len(edges) == 1


# ---------------------------------------------------------------------------
# Fingerprint stability: same (src, field, target) always same fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_stable_for_same_src_field_target():
    obs_a = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="[[Locations/Unknown]]")
    resolve = _resolve_from({})

    _, repairs_a = build_edges([obs_a], resolve=resolve, ids=_ids(), now=NOW)
    obs_b = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="[[Locations/Unknown]]")
    _, repairs_b = build_edges([obs_b], resolve=resolve, ids=SequentialIdFactory("X"), now=NOW)

    assert repairs_a[0].fingerprint == repairs_b[0].fingerprint


def test_fingerprint_differs_for_different_target():
    obs_a = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="[[Locations/Berlin]]")
    obs_b = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="[[Locations/Paris]]")
    resolve = _resolve_from({})

    _, repairs_a = build_edges([obs_a], resolve=resolve, ids=_ids(), now=NOW)
    _, repairs_b = build_edges([obs_b], resolve=resolve, ids=SequentialIdFactory("X"), now=NOW)

    assert repairs_a[0].fingerprint != repairs_b[0].fingerprint


def test_placeholder_fingerprint_stable():
    obs_a = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="Unknown")
    obs_b = obs(entity=_SAMPLE_ENTITY, field="person.lives", value="Unknown")
    resolve = _resolve_from({})

    _, repairs_a = build_edges([obs_a], resolve=resolve, ids=_ids(), now=NOW)
    _, repairs_b = build_edges([obs_b], resolve=resolve, ids=SequentialIdFactory("X"), now=NOW)

    assert repairs_a[0].fingerprint == repairs_b[0].fingerprint
