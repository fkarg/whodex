from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel
from ruamel.yaml import YAML

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
