"""DerivedStore tests: both backends satisfy the contract; SQLite adds durability."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests.store.derived_store_contract import DerivedStoreContract, _change, _reminder, _repair
from whodex.domain.enums import SuggestionStatus
from whodex.store.memory import InMemoryDerivedStore
from whodex.store.sqlite import SqliteDerivedStore


class TestInMemoryDerivedStore(DerivedStoreContract):
    def make_store(self) -> InMemoryDerivedStore:
        return InMemoryDerivedStore()


class TestSqliteDerivedStore(DerivedStoreContract):
    def make_store(self) -> SqliteDerivedStore:
        return SqliteDerivedStore(url="sqlite://")


class TestSqliteDerivedStoreDurability:
    """Derived rows written to a real file survive across store instances."""

    def test_changes_survive_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "derived.db"
            url = f"sqlite:///{db_path}"

            store_a = SqliteDerivedStore(url=url)
            c = _change(fingerprint="fp-durable")
            store_a.replace_changes([c])

            store_b = SqliteDerivedStore(url=url)
            result = store_b.changes()
            assert len(result) == 1
            assert result[0].fingerprint == "fp-durable"
            assert result[0].entity_id == c.entity_id

    def test_repairs_survive_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "derived_repairs.db"
            url = f"sqlite:///{db_path}"

            store_a = SqliteDerivedStore(url=url)
            r = _repair(fingerprint="fp-repair-durable")
            store_a.replace_repairs([r])

            store_b = SqliteDerivedStore(url=url)
            result = store_b.repairs()
            assert len(result) == 1
            assert result[0].fingerprint == "fp-repair-durable"

    def test_reminders_survive_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "derived_reminders.db"
            url = f"sqlite:///{db_path}"

            store_a = SqliteDerivedStore(url=url)
            rem = _reminder(fingerprint="fp-rem-durable")
            store_a.replace_reminders([rem])

            store_b = SqliteDerivedStore(url=url)
            result = store_b.reminders()
            assert len(result) == 1
            assert result[0].fingerprint == "fp-rem-durable"

    def test_user_state_overlay_survives_across_store_instances(self) -> None:
        """Acked changes stay seen=True across store instances (durability + overlay)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "derived_overlay.db"
            url = f"sqlite:///{db_path}"

            fp = "fp-durable-overlay"
            c = _change(fingerprint=fp)

            store_a = SqliteDerivedStore(url=url)
            store_a.replace_changes([c], acked_fingerprints={fp})

            # New instance: overlay must survive
            store_b = SqliteDerivedStore(url=url)
            # Re-sync with the same item — overlay should persist
            store_b.replace_changes([c])
            result = store_b.changes()
            assert len(result) == 1
            assert result[0].seen is True

    def test_repair_dismissed_survives_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "derived_repair_overlay.db"
            url = f"sqlite:///{db_path}"

            fp = "fp-repair-durable-overlay"
            r = _repair(fingerprint=fp)

            store_a = SqliteDerivedStore(url=url)
            store_a.replace_repairs([r], dismissed_fingerprints={fp})

            store_b = SqliteDerivedStore(url=url)
            store_b.replace_repairs([r])
            result = store_b.repairs()
            assert len(result) == 1
            assert result[0].status == SuggestionStatus.dismissed
