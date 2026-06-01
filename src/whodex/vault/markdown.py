from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from whodex.domain.refs import EntityRef

_yaml = YAML(typ="rt")  # round-trip loader preserves all keys


def _yaml_to_plain(obj: Any) -> Any:
    """Recursively convert ruamel.yaml objects to plain Python types."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _yaml_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_yaml_to_plain(item) for item in obj]
    # ruamel scalar types (CommentedSeq, ScalarString, etc.) all have str/int/float/bool
    # representations — convert to primitive via their underlying Python type.
    for base in (bool, int, float, str):
        if isinstance(obj, base):
            return base(obj)
    # Fallback: stringify
    return str(obj)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Split *text* into (frontmatter_dict, body).

    The frontmatter fence must start at byte 0: text must begin with '---\\n'.
    The block ends at the first line that is exactly '---' or '...' (no trailing
    spaces). Everything after that closing fence line is the body (verbatim).

    Returns ({}, text) when no valid opening fence is found.
    """
    if not text.startswith("---\n"):
        return {}, text

    # Search for closing fence starting after the opening fence line
    rest = text[4:]  # everything after "---\n"
    closing_idx = None
    closing_end = None
    for line_end in _iter_line_ends(rest):
        line = rest[line_end[0] : line_end[1]]
        stripped = line.rstrip("\n").rstrip("\r")
        if stripped in ("---", "..."):
            closing_idx = line_end[0]
            closing_end = line_end[1]
            break

    if closing_idx is None:
        # No closing fence found → not valid frontmatter
        return {}, text

    yaml_block = rest[:closing_idx]
    body = rest[closing_end:]

    parsed = _yaml.load(io.StringIO(yaml_block))
    frontmatter: dict[str, Any] = {} if parsed is None else _yaml_to_plain(parsed)
    return frontmatter, body


def _iter_line_ends(text: str) -> Iterator[tuple[int, int]]:
    """Yield (start, end) byte offsets for each line in *text* (end includes the newline)."""
    start = 0
    while start < len(text):
        nl = text.find("\n", start)
        if nl == -1:
            yield start, len(text)
            break
        yield start, nl + 1
        start = nl + 1


class ParsedNote(BaseModel):
    frontmatter: dict[str, Any]  # parsed YAML mapping ({} if none)
    body: str  # everything after the closing fence, byte-verbatim
    raw: str  # the original full text

    model_config = {"frozen": True}

    def refs(self, key: str) -> list[EntityRef]:
        """
        Return EntityRef objects for frontmatter[key].

        The value may be:
        - absent / None / empty list → []
        - a single string → [EntityRef.parse(value)]
        - a list of strings → [EntityRef.parse(v) for v in value]
        """
        value = self.frontmatter.get(key)
        if not value:
            return []
        if isinstance(value, list):
            return [EntityRef.parse(str(v)) for v in value if v]
        return [EntityRef.parse(str(value))]


def parse_note(text: str) -> ParsedNote:
    """Parse an Obsidian-style markdown note into frontmatter + body."""
    frontmatter, body = _parse_frontmatter(text)
    return ParsedNote(frontmatter=frontmatter, body=body, raw=text)


def _extract_frontmatter_text(raw: str) -> tuple[str, str]:
    """
    Return (frontmatter_yaml_block, body) where *frontmatter_yaml_block* is the
    raw YAML text between the ``---`` fences (without the fence lines themselves)
    and *body* is everything after the closing fence, byte-verbatim.

    Returns ("", raw) when no valid frontmatter block is found.
    """
    if not raw.startswith("---\n"):
        return "", raw

    rest = raw[4:]
    for line_end in _iter_line_ends(rest):
        line = rest[line_end[0] : line_end[1]]
        stripped = line.rstrip("\n").rstrip("\r")
        if stripped in ("---", "..."):
            yaml_block = rest[: line_end[0]]
            body = rest[line_end[1] :]
            return yaml_block, body

    # No closing fence → not valid frontmatter
    return "", raw


def _build_commented_map(changes: dict[str, Any], set_uid: str | None) -> CommentedMap:
    """Build a fresh CommentedMap from *changes* and an optional uid."""
    cm = CommentedMap()
    for k, v in changes.items():
        cm[k] = v
    if set_uid is not None:
        whodex_map: CommentedMap = CommentedMap()
        whodex_map["uid"] = set_uid
        cm["whodex"] = whodex_map
    return cm


def _apply_changes_to_map(
    cm: CommentedMap,
    changes: dict[str, Any],
    set_uid: str | None,
) -> None:
    """Apply *changes* and optional uid injection to *cm* in-place."""
    for k, v in changes.items():
        cm[k] = v

    if set_uid is None:
        return

    if "whodex" not in cm:
        whodex_map: CommentedMap = CommentedMap()
        whodex_map["uid"] = set_uid
        cm["whodex"] = whodex_map
    else:
        existing_whodex = cm["whodex"]
        # Fix 2: scalar whodex value (e.g. ``whodex: junk``) — replace wholesale.
        if not isinstance(existing_whodex, dict):
            fresh: CommentedMap = CommentedMap()
            fresh["uid"] = set_uid
            cm["whodex"] = fresh
            return
        # Fix 1: treat empty/falsy uid as absent so we fill it in.
        if not existing_whodex.get("uid"):
            existing_whodex["uid"] = set_uid


def render_with_changes(
    raw: str,
    changes: dict[str, Any],
    *,
    set_uid: str | None = None,
) -> str:
    """Return *raw* with only the given frontmatter *changes* applied (and
    ``whodex.uid`` set if *set_uid* is given and not already present). Body is
    byte-verbatim. Untouched frontmatter keys keep their original formatting
    (ruamel round-trip). If *raw* has no frontmatter and changes/uid are given,
    a frontmatter block is created.
    """
    yaml_block, body = _extract_frontmatter_text(raw)

    if yaml_block == "" and not raw.startswith("---\n"):
        # No existing frontmatter
        if changes or set_uid is not None:
            fresh = _build_commented_map(changes, set_uid)
            buf = io.StringIO()
            _yaml.dump(fresh, buf)
            return f"---\n{buf.getvalue()}---\n{raw}"
        return raw

    # Load existing YAML block with round-trip loader
    loaded = _yaml.load(io.StringIO(yaml_block))
    cm: CommentedMap = CommentedMap() if loaded is None else loaded
    _apply_changes_to_map(cm, changes, set_uid)

    buf = io.StringIO()
    _yaml.dump(cm, buf)
    return f"---\n{buf.getvalue()}---\n{body}"


def render_note(note: ParsedNote) -> str:
    """Re-render *note* with no changes applied (convenience wrapper)."""
    return render_with_changes(note.raw, {})
