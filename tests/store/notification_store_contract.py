"""Behavioural contract every NotificationStore must satisfy.

Subclass and override ``make_store`` to instantiate the backend under test.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from whodex.domain.state import Notification
from whodex.store.memory import InMemoryNotificationStore
from whodex.store.sqlite import SqliteNotificationStore

_T0 = __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)


def _n(
    nid: str = "N-001",
    *,
    kind: str = "change",
    entity_id: str = "E1",
    dedupe_key: str = "dk-001",
    delivered_to: list[str] | None = None,
) -> Notification:
    return Notification(
        id=nid,
        kind=kind,
        entity_id=entity_id,
        payload={"field": "job.title"},
        dedupe_key=dedupe_key,
        created_at=_T0,
        delivered_to=delivered_to or [],
    )


class NotificationStoreContract:
    def make_store(self):  # override -> returns a fresh NotificationStore
        raise NotImplementedError

    # ── round-trip ────────────────────────────────────────────────────────────

    def test_append_and_all_round_trip(self) -> None:
        store = self.make_store()
        n = _n()
        store.append([n])
        result = store.all()
        assert len(result) == 1
        r = result[0]
        assert r.id == n.id
        assert r.kind == n.kind
        assert r.entity_id == n.entity_id
        assert r.dedupe_key == n.dedupe_key
        assert r.state == "pending"
        assert r.delivered_to == []

    def test_pending_returns_only_pending(self) -> None:
        store = self.make_store()
        store.append([_n("N-001", dedupe_key="dk-001")])
        store.append([_n("N-002", dedupe_key="dk-002")])
        assert len(store.pending()) == 2

    def test_empty_store(self) -> None:
        store = self.make_store()
        assert store.all() == []
        assert store.pending() == []

    # ── mark_delivered ────────────────────────────────────────────────────────

    def test_mark_delivered_adds_sink(self) -> None:
        store = self.make_store()
        n = _n()
        store.append([n])
        store.mark_delivered(n.id, "tui")
        result = store.all()
        assert len(result) == 1
        assert "tui" in result[0].delivered_to

    def test_mark_delivered_idempotent(self) -> None:
        """Calling mark_delivered twice for same (id, sink) does not duplicate."""
        store = self.make_store()
        n = _n()
        store.append([n])
        store.mark_delivered(n.id, "tui")
        store.mark_delivered(n.id, "tui")
        result = store.all()
        assert result[0].delivered_to.count("tui") == 1

    def test_mark_delivered_unknown_id_is_no_op(self) -> None:
        store = self.make_store()
        store.mark_delivered("NONEXISTENT", "tui")  # must not raise

    def test_pending_still_returns_notification_after_partial_delivery(self) -> None:
        """A notification with some sinks delivered is still pending (state unchanged)."""
        store = self.make_store()
        n = _n()
        store.append([n])
        store.mark_delivered(n.id, "tui")
        # state is still "pending" — dispatcher decides finality, not the store
        assert len(store.pending()) == 1

    # ── dedupe: append same dedupe_key twice → one row ────────────────────────

    def test_append_same_dedupe_key_is_no_op(self) -> None:
        store = self.make_store()
        n1 = _n("N-001", dedupe_key="dk-same")
        n2 = _n("N-002", dedupe_key="dk-same")  # different id, same dedupe_key
        store.append([n1])
        store.append([n2])
        result = store.all()
        assert len(result) == 1
        assert result[0].id == "N-001"  # first one wins

    def test_append_same_dedupe_key_in_batch_is_no_op(self) -> None:
        """Duplicates within a single append call: only the first is stored."""
        store = self.make_store()
        n1 = _n("N-001", dedupe_key="dk-same")
        n2 = _n("N-002", dedupe_key="dk-same")
        store.append([n1, n2])
        assert len(store.all()) == 1

    def test_different_dedupe_keys_stored_separately(self) -> None:
        store = self.make_store()
        store.append(
            [
                _n("N-001", dedupe_key="dk-a"),
                _n("N-002", dedupe_key="dk-b"),
            ]
        )
        assert len(store.all()) == 2


# ── concrete backend fixtures ─────────────────────────────────────────────────


class TestInMemoryNotificationStore(NotificationStoreContract):
    def make_store(self) -> InMemoryNotificationStore:
        return InMemoryNotificationStore()


class TestSqliteNotificationStore(NotificationStoreContract):
    def make_store(self) -> SqliteNotificationStore:
        return SqliteNotificationStore(url="sqlite://")


class TestSqliteNotificationStoreDurability:
    """Rows written to a real file survive across store instances."""

    def test_notifications_survive_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "notifications.db"
            url = f"sqlite:///{db_path}"

            store_a = SqliteNotificationStore(url=url)
            n = _n("N-001", dedupe_key="dk-durable")
            store_a.append([n])

            store_b = SqliteNotificationStore(url=url)
            result = store_b.all()
            assert len(result) == 1
            assert result[0].id == "N-001"
            assert result[0].dedupe_key == "dk-durable"

    def test_mark_delivered_survives_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "notifications_delivery.db"
            url = f"sqlite:///{db_path}"

            store_a = SqliteNotificationStore(url=url)
            n = _n("N-001", dedupe_key="dk-delivery")
            store_a.append([n])
            store_a.mark_delivered("N-001", "tui")

            store_b = SqliteNotificationStore(url=url)
            result = store_b.all()
            assert len(result) == 1
            assert "tui" in result[0].delivered_to

    def test_dedupe_survives_across_store_instances(self) -> None:
        """Attempting to append the same dedupe_key after a restart is a no-op."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "notifications_dedupe.db"
            url = f"sqlite:///{db_path}"

            store_a = SqliteNotificationStore(url=url)
            store_a.append([_n("N-001", dedupe_key="dk-x")])

            store_b = SqliteNotificationStore(url=url)
            store_b.append([_n("N-002", dedupe_key="dk-x")])  # duplicate key
            assert len(store_b.all()) == 1
