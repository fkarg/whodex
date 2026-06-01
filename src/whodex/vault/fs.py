"""Vault filesystem scanner.

Yields VaultFile objects for every .md file in a vault directory, skipping
system/hidden folders and dotfiles.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

__all__ = ["VaultFile", "scan"]

# Top-level directory names to skip entirely (case-sensitive, Obsidian conventions)
_SKIP_DIRS: frozenset[str] = frozenset({".obsidian", ".whodex", ".trash"})


@dataclass(frozen=True)
class VaultFile:
    path: str  # relative path, e.g. "People/Jane Doe.md"
    folder: str  # first path segment, e.g. "People"
    stem: str  # filename without .md, e.g. "Jane Doe"
    text: str  # full file contents


def scan(vault_dir: Path) -> Iterable[VaultFile]:
    """Yield one VaultFile per .md file found in *vault_dir*.

    Skips:
    - Any top-level directory whose name is in _SKIP_DIRS
    - Any path segment starting with '.' (dotfiles / hidden directories)
    - Files whose stem starts with '.'
    """
    vault_dir = vault_dir.resolve()
    for md_file in vault_dir.rglob("*.md"):
        rel = md_file.relative_to(vault_dir)
        parts = rel.parts  # e.g. ("People", "Jane Doe.md")

        # Skip if any segment is hidden (starts with '.')
        if any(part.startswith(".") for part in parts):
            continue

        # Skip if the first segment is a system folder
        top = parts[0] if len(parts) > 1 else ""
        if top in _SKIP_DIRS:
            continue

        folder = parts[0] if len(parts) > 1 else ""
        stem = md_file.stem
        text = md_file.read_text(encoding="utf-8", errors="replace")

        yield VaultFile(
            path=str(rel),
            folder=folder,
            stem=stem,
            text=text,
        )
