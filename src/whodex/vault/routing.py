"""Entity routing: maps (folder, type_, tags) -> (EntityKind, subtype | None).

Precedence: folder > type_ > tags > default.

The subtype is the raw ``type_`` value when it is not the bare kind name
(e.g. "Startup", "City"), otherwise None.  When ``type_`` is None the
subtype is always None.

Default kind when nothing matches: ``EntityKind.person`` (most notes are
people).
"""

from __future__ import annotations

from whodex.domain.enums import EntityKind

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

# First path segment → EntityKind
_FOLDER_MAP: dict[str, EntityKind] = {
    "People": EntityKind.person,
    "Organisations": EntityKind.organisation,
    "Locations": EntityKind.location,
    "Events": EntityKind.event,
}

# type_ value → EntityKind  (case-sensitive, matching real vault usage)
_TYPE_MAP: dict[str, EntityKind] = {
    "Person": EntityKind.person,
    "Organisation": EntityKind.organisation,
    "Organization": EntityKind.organisation,
    "Location": EntityKind.location,
    "City": EntityKind.location,
    "Country": EntityKind.location,
    "Address": EntityKind.location,
    "Region": EntityKind.location,
    "Event": EntityKind.event,
    # Startup and other org subtypes
    "Startup": EntityKind.organisation,
    "Company": EntityKind.organisation,
    "NGO": EntityKind.organisation,
    "University": EntityKind.organisation,
    "Government": EntityKind.organisation,
    "Fraternity": EntityKind.organisation,
}

# tag value → EntityKind
_TAG_MAP: dict[str, EntityKind] = {
    "Person": EntityKind.person,
    "Organisation": EntityKind.organisation,
    "Organization": EntityKind.organisation,
    "Location": EntityKind.location,
    "Event": EntityKind.event,
}

# Bare kind names — these do NOT become subtypes
_BARE_KIND_NAMES: frozenset[str] = frozenset(
    {"Person", "Organisation", "Organization", "Location", "Event"}
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def route(
    folder: str,
    type_: str | None,
    tags: list[str],
) -> tuple[EntityKind, str | None]:
    """Return ``(EntityKind, subtype)`` for a note described by its vault path's
    first segment (*folder*), its frontmatter ``type`` field (*type_*) and its
    frontmatter ``tags`` list (*tags*).

    Precedence: folder > type_ > tags > default (person).

    *subtype* is ``type_`` when it is not a bare kind name, else ``None``.
    """
    # 1. Folder: use only the first path segment so nested folders still match.
    first_segment = folder.split("/")[0] if folder else ""
    kind = _FOLDER_MAP.get(first_segment)

    # 2. type_ fallback
    if kind is None and type_:
        kind = _TYPE_MAP.get(type_)

    # 3. tags fallback
    if kind is None:
        for tag in tags:
            candidate = _TAG_MAP.get(tag)
            if candidate is not None:
                kind = candidate
                break

    # 4. Default
    if kind is None:
        kind = EntityKind.person

    # Subtype: type_ unless it is a bare kind name or None
    subtype: str | None = None
    if type_ and type_ not in _BARE_KIND_NAMES:
        subtype = type_

    return kind, subtype
