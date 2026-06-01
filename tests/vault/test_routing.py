"""Tests for whodex.vault.routing — behavioral/table-driven, no internals."""
from __future__ import annotations

import pytest

from whodex.domain.enums import EntityKind
from whodex.vault.routing import route


# ---------------------------------------------------------------------------
# Routing table: (folder, type_, tags) -> EntityKind
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "folder,type_,tags,kind",
    [
        ("People", "Person", ["Person"], EntityKind.person),
        ("People/Inactive", "Person", [], EntityKind.person),
        ("People/Family", None, [], EntityKind.person),
        ("Organisations", "Startup", ["Organisation"], EntityKind.organisation),
        ("Organisations", "Organisation", ["Organisation"], EntityKind.organisation),
        ("Organisations/Fraternity", None, ["Organisation"], EntityKind.organisation),
        ("Locations", "City", ["Location"], EntityKind.location),
        ("Locations", "Country", [], EntityKind.location),
        ("Events", "Event", ["Event"], EntityKind.event),
    ],
)
def test_routing_table(folder: str, type_: str | None, tags: list[str], kind: EntityKind) -> None:
    assert route(folder, type_, tags)[0] == kind


# ---------------------------------------------------------------------------
# Subtype extraction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "folder,type_,expected_subtype",
    [
        ("Organisations", "Startup", "Startup"),
        ("Locations", "City", "City"),
        ("People", "Person", None),
        ("Organisations", "Organisation", None),
        ("People", None, None),
    ],
)
def test_subtype(folder: str, type_: str | None, expected_subtype: str | None) -> None:
    assert route(folder, type_, [])[1] == expected_subtype


# ---------------------------------------------------------------------------
# Precedence invariants
# ---------------------------------------------------------------------------

def test_folder_beats_conflicting_type_and_tags() -> None:
    """Folder says People; type/tags say Organisation -> folder wins."""
    assert route("People", "Organisation", ["Organisation"])[0] == EntityKind.person


def test_type_used_when_folder_is_unknown() -> None:
    assert route("Inbox", "City", [])[0] == EntityKind.location


def test_tags_used_when_folder_and_type_unknown() -> None:
    assert route("Inbox", None, ["Event"])[0] == EntityKind.event


# ---------------------------------------------------------------------------
# Default fallback
# ---------------------------------------------------------------------------

def test_default_is_person_when_nothing_matches() -> None:
    """When folder/type/tags give no signal, default is person."""
    assert route("Inbox", None, [])[0] == EntityKind.person
    assert route("", None, [])[0] == EntityKind.person


# ---------------------------------------------------------------------------
# Nested folder paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "folder,kind",
    [
        ("People/Inactive", EntityKind.person),
        ("People/Family/Nuclear", EntityKind.person),
        ("Organisations/Fraternities/Active", EntityKind.organisation),
        ("Locations/Europe/Cities", EntityKind.location),
        ("Events/2024/Conferences", EntityKind.event),
    ],
)
def test_nested_folders_resolve_to_top_level_kind(folder: str, kind: EntityKind) -> None:
    assert route(folder, None, [])[0] == kind


# ---------------------------------------------------------------------------
# Location subtypes (City, Country, Address, Region)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("loc_type", ["City", "Country", "Address", "Region"])
def test_location_subtypes_are_preserved(loc_type: str) -> None:
    kind, subtype = route("Locations", loc_type, [])
    assert kind == EntityKind.location
    assert subtype == loc_type
