"""Behavioural contract every TokenStore must satisfy.

Subclass and override ``make_store`` to run the full suite against any backend.
"""

from __future__ import annotations

from datetime import UTC, datetime

_CREATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_PLAINTEXT = "super-secret-token-abc123"


class TokenStoreContract:
    def make_store(self):  # override → returns a fresh TokenStore
        raise NotImplementedError

    # ── issue + validate round-trip ───────────────────────────────────────────

    def test_validate_issued_token_returns_true(self) -> None:
        store = self.make_store()
        store.issue("firefox", token=_PLAINTEXT, created_at=_CREATED_AT)
        assert store.validate(_PLAINTEXT) is True

    def test_validate_unknown_token_returns_false(self) -> None:
        store = self.make_store()
        assert store.validate("garbage-token-not-in-store") is False

    def test_validate_wrong_token_returns_false(self) -> None:
        store = self.make_store()
        store.issue("my-label", token=_PLAINTEXT, created_at=_CREATED_AT)
        assert store.validate("not-" + _PLAINTEXT) is False

    def test_issue_returns_token_id_string(self) -> None:
        store = self.make_store()
        token_id = store.issue("lbl", token=_PLAINTEXT, created_at=_CREATED_AT)
        assert isinstance(token_id, str)
        assert token_id  # non-empty

    # ── revoke ────────────────────────────────────────────────────────────────

    def test_revoked_token_fails_validate(self) -> None:
        store = self.make_store()
        token_id = store.issue("lbl", token=_PLAINTEXT, created_at=_CREATED_AT)
        store.revoke(token_id)
        assert store.validate(_PLAINTEXT) is False

    def test_revoke_does_not_affect_other_tokens(self) -> None:
        store = self.make_store()
        token_id = store.issue("first", token="token-aaa", created_at=_CREATED_AT)
        store.issue("second", token="token-bbb", created_at=_CREATED_AT)
        store.revoke(token_id)
        assert store.validate("token-bbb") is True
        assert store.validate("token-aaa") is False

    # ── security invariant: only hash stored ─────────────────────────────────

    def test_stored_hash_differs_from_plaintext(self) -> None:
        """The raw plaintext must NEVER appear in the stored rows."""
        from whodex.domain.tokens import hash_token

        store = self.make_store()
        store.issue("sec", token=_PLAINTEXT, created_at=_CREATED_AT)
        rows = store.list_tokens()
        assert rows, "expected at least one token row"
        for row in rows:
            # The hash field should not equal the plaintext
            assert row.token_hash != _PLAINTEXT
            # And it should equal hash_token(plaintext)
            assert row.token_hash == hash_token(_PLAINTEXT)

    # ── list_tokens ───────────────────────────────────────────────────────────

    def test_list_tokens_empty_on_fresh_store(self) -> None:
        store = self.make_store()
        assert store.list_tokens() == []

    def test_list_tokens_includes_issued_token(self) -> None:
        store = self.make_store()
        store.issue("my-label", token=_PLAINTEXT, created_at=_CREATED_AT)
        rows = store.list_tokens()
        assert len(rows) == 1
        assert rows[0].label == "my-label"
        assert rows[0].revoked is False

    def test_list_tokens_shows_revoked_status(self) -> None:
        store = self.make_store()
        token_id = store.issue("rev-label", token=_PLAINTEXT, created_at=_CREATED_AT)
        store.revoke(token_id)
        rows = store.list_tokens()
        assert len(rows) == 1
        assert rows[0].revoked is True

    def test_list_tokens_multiple(self) -> None:
        store = self.make_store()
        store.issue("a", token="token-a", created_at=_CREATED_AT)
        store.issue("b", token="token-b", created_at=_CREATED_AT)
        rows = store.list_tokens()
        labels = {r.label for r in rows}
        assert labels == {"a", "b"}
