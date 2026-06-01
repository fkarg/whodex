"""SqliteSyncTokenStore satisfies the SyncTokenStore contract + cross-instance durability."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests.store.sync_token_store_contract import SyncTokenStoreContract
from whodex.store.sqlite import SqliteSyncTokenStore


class TestSqliteSyncTokenStore(SyncTokenStoreContract):
    def make_store(self) -> SqliteSyncTokenStore:
        return SqliteSyncTokenStore(url="sqlite://")

    # ── SQLite-specific: real-file cross-instance durability ─────────────────

    def test_data_persists_across_instances(self) -> None:
        """Two separate store instances opened against the same file share state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sync_tokens.db"
            url = f"sqlite:///{db_path}"

            store1 = SqliteSyncTokenStore(url=url)
            store1.set("google_contacts", "T_PERSISTED")

            store2 = SqliteSyncTokenStore(url=url)
            assert store2.get("google_contacts") == "T_PERSISTED"

    def test_clear_persists_across_instances(self) -> None:
        """clear() in one instance is reflected in a new instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sync_tokens.db"
            url = f"sqlite:///{db_path}"

            store1 = SqliteSyncTokenStore(url=url)
            store1.set("google_contacts", "T1")
            store1.clear("google_contacts")

            store2 = SqliteSyncTokenStore(url=url)
            assert store2.get("google_contacts") is None
