"""SqliteTokenStore satisfies the TokenStore contract + real-file durability."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from tests.store.token_store_contract import TokenStoreContract
from whodex.store.sqlite import SqliteTokenStore

_CREATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class TestSqliteTokenStore(TokenStoreContract):
    def make_store(self) -> SqliteTokenStore:
        from whodex.domain.ids import SequentialIdFactory

        return SqliteTokenStore(url="sqlite://", id_factory=SequentialIdFactory("TK"))

    # ── SQLite-specific: real-file cross-instance durability ─────────────────

    def test_data_persists_across_instances(self) -> None:
        """Two separate store instances opened against the same file share state."""
        from whodex.domain.ids import SequentialIdFactory

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tokens.db"
            url = f"sqlite:///{db_path}"

            store1 = SqliteTokenStore(url=url, id_factory=SequentialIdFactory("TK"))
            store1.issue("persisted", token="my-durable-token", created_at=_CREATED_AT)

            store2 = SqliteTokenStore(url=url, id_factory=SequentialIdFactory("TK"))
            assert store2.validate("my-durable-token") is True
