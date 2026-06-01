"""Behavioural contract every VaultStateStore must satisfy.

Subclass and override ``make_store`` to run the full suite against any backend.
"""

from __future__ import annotations

from whodex.domain.state import VaultFileState


def _make_state(
    path: str = "People/Jane.md",
    last_content_hash: str = "abc123",
    last_frontmatter_seen: dict | None = None,
    last_mtime: float = 1_700_000_000.0,
    last_written_hash: str | None = None,
) -> VaultFileState:
    return VaultFileState(
        path=path,
        last_content_hash=last_content_hash,
        last_frontmatter_seen=last_frontmatter_seen or {"uid": "UID-001"},
        last_mtime=last_mtime,
        last_written_hash=last_written_hash,
    )


class VaultStateStoreContract:
    def make_store(self):  # override -> returns a fresh VaultStateStore
        raise NotImplementedError

    # ── put + get round-trip ──────────────────────────────────────────────────

    def test_put_then_get_returns_same_state(self) -> None:
        s = self.make_store()
        state = _make_state()
        s.put(state)
        result = s.get("People/Jane.md")
        assert result is not None
        assert result.path == "People/Jane.md"
        assert result.last_content_hash == "abc123"
        assert result.last_mtime == 1_700_000_000.0
        assert result.last_written_hash is None

    def test_put_then_get_preserves_last_written_hash(self) -> None:
        s = self.make_store()
        state = _make_state(last_written_hash="deadbeef")
        s.put(state)
        result = s.get("People/Jane.md")
        assert result is not None
        assert result.last_written_hash == "deadbeef"

    def test_put_then_get_preserves_frontmatter(self) -> None:
        s = self.make_store()
        fm = {"uid": "UID-999", "name": "Jane Doe", "tags": ["crm"]}
        state = _make_state(last_frontmatter_seen=fm)
        s.put(state)
        result = s.get("People/Jane.md")
        assert result is not None
        assert result.last_frontmatter_seen == fm

    # ── unknown path returns None ────────────────────────────────────────────

    def test_get_unknown_path_returns_none(self) -> None:
        s = self.make_store()
        assert s.get("does/not/exist.md") is None

    def test_get_on_empty_store_returns_none(self) -> None:
        s = self.make_store()
        assert s.get("anything.md") is None

    # ── upsert (second put for same path → one row, latest wins) ─────────────

    def test_upsert_second_put_overwrites_first(self) -> None:
        s = self.make_store()
        s.put(_make_state(last_content_hash="hash-v1", last_mtime=1_000.0))
        s.put(_make_state(last_content_hash="hash-v2", last_mtime=2_000.0))
        result = s.get("People/Jane.md")
        assert result is not None
        assert result.last_content_hash == "hash-v2"
        assert result.last_mtime == 2_000.0

    def test_upsert_produces_single_row(self) -> None:
        s = self.make_store()
        s.put(_make_state(path="a.md"))
        s.put(_make_state(path="a.md"))
        assert len(s.all()) == 1

    # ── all() ────────────────────────────────────────────────────────────────

    def test_all_empty_store_returns_empty_list(self) -> None:
        s = self.make_store()
        assert s.all() == []

    def test_all_returns_all_stored_states(self) -> None:
        s = self.make_store()
        s.put(_make_state(path="a.md"))
        s.put(_make_state(path="b.md"))
        paths = {st.path for st in s.all()}
        assert paths == {"a.md", "b.md"}

    def test_all_does_not_accumulate_across_upserts(self) -> None:
        s = self.make_store()
        s.put(_make_state(path="a.md"))
        s.put(_make_state(path="a.md"))
        assert len(s.all()) == 1
