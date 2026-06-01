"""Focused unit test for ObsidianSource.fetch echo-suppression skip branch.

This test directly exercises the skip logic at obsidian.py's ``if state is not None
and state.last_written_hash == current_hash: continue`` branch.

Regression guard: this test FAILS if echo suppression is removed from ObsidianSource.fetch.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whodex.domain.state import VaultFileState
from whodex.sources.obsidian import ObsidianSource
from whodex.store.memory import InMemoryVaultStateStore
from whodex.vault.hashing import content_hash

NOW = datetime(2026, 3, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _frontmatter_text(raw: str) -> str:
    """Extract the YAML block between the ``---`` fences (no fence lines).

    Mirrors the private ``_frontmatter_text`` in obsidian.py — duplicated here
    so the test does not depend on private symbols while still computing the
    identical hash basis used by echo suppression.
    """
    if not raw.startswith("---\n"):
        return ""
    rest = raw[4:]
    start = 0
    while start < len(rest):
        nl = rest.find("\n", start)
        end = nl + 1 if nl != -1 else len(rest)
        line = rest[start:end].rstrip("\n").rstrip("\r")
        if line in ("---", "..."):
            return rest[:start]
        start = end
    return ""


def _write_note(vault: Path, rel_path: str, content: str) -> Path:
    full = vault / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    text = textwrap.dedent(content)
    full.write_text(text)
    return full


# ---------------------------------------------------------------------------
# Unit test: skip branch fires when last_written_hash matches
# ---------------------------------------------------------------------------


def test_fetch_skips_file_when_last_written_hash_matches(tmp_path: Path) -> None:
    """ObsidianSource.fetch yields NO RawRecord for a file whose current frontmatter
    hash matches VaultFileState.last_written_hash (echo-suppression skip branch).

    This is a regression guard: if the ``continue`` in the skip branch is removed,
    the fetch will yield a record and the assertion will fail.
    """
    content = textwrap.dedent(
        """\
        ---
        type: Person
        emails: [echo@example.com]
        whodex:
          uid: TESTUID
        ---
        body text
        """
    )
    note_path = _write_note(tmp_path, "People/Echo.md", content)
    actual_content = note_path.read_text()

    # Compute the hash exactly as write_back would after writing this content.
    fm_text = _frontmatter_text(actual_content)
    written_hash = content_hash(fm_text)

    # Pre-populate the state store so fetch thinks whodex last wrote this file.
    state_store = InMemoryVaultStateStore()
    state_store.put(
        VaultFileState(
            path="People/Echo.md",
            last_content_hash=written_hash,
            last_frontmatter_seen={},
            last_mtime=0.0,
            last_written_hash=written_hash,  # ← the key field for echo suppression
        )
    )

    source = ObsidianSource(tmp_path, state_store=state_store)
    records = list(source.fetch(None))

    # The file must be skipped entirely — no RawRecord for it.
    paths_yielded = [r.identity.get("vault_path") for r in records]
    assert "People/Echo.md" not in paths_yielded, (
        "Echo suppression FAIL: fetch yielded a record for a file whose "
        "last_written_hash matches the current frontmatter hash. "
        f"Records yielded: {paths_yielded!r}\n"
        "If this test fails after removing the ``continue`` in obsidian.py:~109, "
        "that is the expected regression."
    )


def test_fetch_yields_record_without_matching_written_hash(tmp_path: Path) -> None:
    """ObsidianSource.fetch yields a RawRecord when the state store has NO entry
    for the file (or a non-matching hash) — i.e., suppression does NOT fire for
    normal files that whodex has not written.
    """
    _write_note(
        tmp_path,
        "People/Normal.md",
        """\
        ---
        type: Person
        emails: [normal@example.com]
        ---
        body
        """,
    )

    # Empty state store — no last_written_hash → suppression must NOT fire.
    state_store = InMemoryVaultStateStore()
    source = ObsidianSource(tmp_path, state_store=state_store)
    records = list(source.fetch(None))

    paths_yielded = [r.identity.get("vault_path") for r in records]
    assert "People/Normal.md" in paths_yielded, (
        "fetch did not yield a record for a normal (unwritten) file. "
        f"Records yielded: {paths_yielded!r}"
    )


@pytest.mark.parametrize("wrong_hash", ["0000000000000000", ""])
def test_fetch_yields_record_when_hash_differs(tmp_path: Path, wrong_hash: str) -> None:
    """ObsidianSource.fetch does NOT suppress when the stored hash doesn't match
    the current file content (e.g., the file was edited externally).
    """
    content = textwrap.dedent(
        """\
        ---
        type: Person
        emails: [changed@example.com]
        ---
        body
        """
    )
    _write_note(tmp_path, "People/Changed.md", content)

    state_store = InMemoryVaultStateStore()
    state_store.put(
        VaultFileState(
            path="People/Changed.md",
            last_content_hash=wrong_hash,
            last_frontmatter_seen={},
            last_mtime=0.0,
            last_written_hash=wrong_hash,  # does not match current content
        )
    )

    source = ObsidianSource(tmp_path, state_store=state_store)
    records = list(source.fetch(None))

    paths_yielded = [r.identity.get("vault_path") for r in records]
    assert "People/Changed.md" in paths_yielded, (
        "fetch incorrectly suppressed a file with a non-matching written hash. "
        f"Records yielded: {paths_yielded!r}"
    )
