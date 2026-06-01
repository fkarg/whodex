from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from whodex.vault.markdown import parse_note, render_with_changes


def _is_empty(value: Any) -> bool:
    """Return True when *value* is considered absent/empty for fill-blank logic."""
    if value is None:
        return True
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, str):
        return value == ""
    return False


class WriteBackResult(BaseModel):
    new_text: str | None  # None == no change (caller writes nothing -> byte-identical file)
    wrote_fields: list[str]  # which managed frontmatter keys were written
    injected_uid: bool


def plan_writeback(
    *,
    raw: str,
    projected: dict[str, Any],
    managed_fields: Sequence[str],
    uid: str | None = None,
) -> WriteBackResult:
    """Compute the write-back for a vault note without performing I/O.

    Only FILLS blanks — never overwrites a field that is already present with a
    non-empty value (Obsidian wins / no-clobber).  Non-managed keys and the body
    are never touched.

    Parameters
    ----------
    raw:
        Current on-disk note text.
    projected:
        Canonical values available to fill in (managed keys only).
    managed_fields:
        Frontmatter keys whodex may fill.
    uid:
        ``whodex.uid`` to inject if the note does not already have one.

    Returns
    -------
    WriteBackResult
        ``new_text=None`` when there is nothing to change (idempotent no-op for
        the caller — writing the file would produce a byte-identical result).
    """
    note = parse_note(raw)

    changes: dict[str, Any] = {}
    for field in managed_fields:
        existing = note.frontmatter.get(field)
        if _is_empty(existing):
            candidate = projected.get(field)
            if not _is_empty(candidate):
                changes[field] = candidate

    # uid injection: only when the note has no whodex.uid yet
    whodex_block = note.frontmatter.get("whodex")
    uid_present = isinstance(whodex_block, dict) and not _is_empty(whodex_block.get("uid"))
    set_uid = uid if (uid is not None and not uid_present) else None
    injected_uid = set_uid is not None

    if not changes and not injected_uid:
        return WriteBackResult(new_text=None, wrote_fields=[], injected_uid=False)

    new_text = render_with_changes(raw, changes, set_uid=set_uid)
    return WriteBackResult(
        new_text=new_text,
        wrote_fields=list(changes.keys()),
        injected_uid=injected_uid,
    )
