"""Behavioural contract every SyncTokenStore must satisfy.

Subclass and override ``make_store`` to run the full suite against any backend.
"""

from __future__ import annotations


class SyncTokenStoreContract:
    def make_store(self):  # override → returns a fresh SyncTokenStore
        raise NotImplementedError

    # ── get on empty store ────────────────────────────────────────────────────

    def test_get_returns_none_when_no_token_set(self) -> None:
        store = self.make_store()
        assert store.get("google_contacts") is None

    def test_get_returns_none_for_unknown_source(self) -> None:
        store = self.make_store()
        store.set("source_a", "token_a")
        assert store.get("source_b") is None

    # ── set + get round-trip ──────────────────────────────────────────────────

    def test_set_then_get_returns_token(self) -> None:
        store = self.make_store()
        store.set("google_contacts", "T1")
        assert store.get("google_contacts") == "T1"

    def test_set_overwrites_previous_token(self) -> None:
        store = self.make_store()
        store.set("google_contacts", "T1")
        store.set("google_contacts", "T2")
        assert store.get("google_contacts") == "T2"

    def test_multiple_sources_are_independent(self) -> None:
        store = self.make_store()
        store.set("source_a", "token_a")
        store.set("source_b", "token_b")
        assert store.get("source_a") == "token_a"
        assert store.get("source_b") == "token_b"

    # ── clear ─────────────────────────────────────────────────────────────────

    def test_clear_removes_token(self) -> None:
        store = self.make_store()
        store.set("google_contacts", "T1")
        store.clear("google_contacts")
        assert store.get("google_contacts") is None

    def test_clear_on_empty_is_noop(self) -> None:
        """clear() on a missing key must not raise."""
        store = self.make_store()
        store.clear("nonexistent_source")  # should not raise

    def test_clear_does_not_affect_other_sources(self) -> None:
        store = self.make_store()
        store.set("source_a", "token_a")
        store.set("source_b", "token_b")
        store.clear("source_a")
        assert store.get("source_a") is None
        assert store.get("source_b") == "token_b"
