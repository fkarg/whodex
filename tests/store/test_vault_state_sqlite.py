"""SqliteVaultStateStore satisfies the VaultStateStore contract + real-file durability."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests.store.vault_state_contract import VaultStateStoreContract
from whodex.domain.state import VaultFileState
from whodex.store.sqlite import SqliteVaultStateStore


class TestSqliteVaultStateStore(VaultStateStoreContract):
    def make_store(self) -> SqliteVaultStateStore:
        return SqliteVaultStateStore(url="sqlite://")

    # ── SQLite-specific: real-file cross-instance durability ─────────────────

    def test_data_persists_across_instances(self) -> None:
        """Two separate store instances opened against the same file share state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "vault_state.db"
            url = f"sqlite:///{db_path}"

            store1 = SqliteVaultStateStore(url=url)
            store1.put(
                VaultFileState(
                    path="People/Jane.md",
                    last_content_hash="persisted-hash",
                    last_frontmatter_seen={"uid": "UID-001"},
                    last_mtime=1_700_000_000.0,
                    last_written_hash=None,
                )
            )

            store2 = SqliteVaultStateStore(url=url)
            result = store2.get("People/Jane.md")

        assert result is not None
        assert result.last_content_hash == "persisted-hash"
        assert result.path == "People/Jane.md"
