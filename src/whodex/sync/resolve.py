"""Resolver factory: wraps an EntityStore to produce a resolve callable
that build_edges can consume.

This module MAY import the store (it is in sync/, not projection/).
"""

from __future__ import annotations

from collections.abc import Callable

from whodex.domain.refs import EntityRef
from whodex.store.interfaces import EntityStore


def make_resolver(entities: EntityStore) -> Callable[[EntityRef], str | None]:
    """Return a callable that maps an EntityRef to a resolved entity_id.

    Resolution strategy (in order):
    1. Look up ``vault_path`` = ``ref.target_path + ".md"``
    2. Look up ``vault_path`` = ``ref.target_path`` (no extension)

    Returns None if the ref has no target_path (placeholder), or if neither
    lookup finds a match.
    """

    def resolve(ref: EntityRef) -> str | None:
        if ref.target_path is None:
            return None
        # Try with .md suffix first
        result = entities.find_by_identifiers([("vault_path", ref.target_path + ".md")])
        if result is not None:
            return result
        # Fallback: without suffix
        return entities.find_by_identifiers([("vault_path", ref.target_path)])

    return resolve
