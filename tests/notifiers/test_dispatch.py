"""Tests for NotificationDispatcher — covers F4 (idempotent delivery)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from whodex.domain.state import Notification
from whodex.notifiers.dispatch import NotificationDispatcher
from whodex.notifiers.impls import TUINotifier
from whodex.notifiers.interface import DeliveryResult
from whodex.store.memory import InMemoryNotificationStore

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _n(nid: str, dedupe_key: str, kind: str = "change") -> Notification:
    return Notification(
        id=nid,
        kind=kind,
        entity_id="E1",
        payload={},
        dedupe_key=dedupe_key,
        created_at=_T0,
    )


# ── helpers ───────────────────────────────────────────────────────────────────


class _NeverNotifier:
    """Notifier whose supports() always returns False."""

    name = "never"

    def supports(self, n: Notification) -> bool:
        return False

    def send(self, n: Notification) -> DeliveryResult:
        raise AssertionError("send() must not be called when supports() is False")


# ── basic dispatch ────────────────────────────────────────────────────────────


def test_dispatch_delivers_to_tui_notifier() -> None:
    store = InMemoryNotificationStore()
    store.append([_n("N-001", "dk-1"), _n("N-002", "dk-2")])

    tui = TUINotifier()
    dispatcher = NotificationDispatcher(notifiers=[tui], store=store)

    count = dispatcher.dispatch()

    assert count == 2
    assert len(tui.delivered) == 2
    delivered_ids = {n.id for n in tui.delivered}
    assert delivered_ids == {"N-001", "N-002"}


def test_dispatch_marks_store_delivered() -> None:
    store = InMemoryNotificationStore()
    store.append([_n("N-001", "dk-1")])

    tui = TUINotifier()
    dispatcher = NotificationDispatcher(notifiers=[tui], store=store)
    dispatcher.dispatch()

    all_ns = store.all()
    assert len(all_ns) == 1
    assert "tui" in all_ns[0].delivered_to


# ── F4: idempotent delivery ───────────────────────────────────────────────────


def test_dispatch_twice_does_not_redeliver() -> None:
    """F4 — calling dispatch() again must not re-deliver already-delivered notifications."""
    store = InMemoryNotificationStore()
    store.append([_n("N-001", "dk-1"), _n("N-002", "dk-2")])

    tui = TUINotifier()
    dispatcher = NotificationDispatcher(notifiers=[tui], store=store)

    first_count = dispatcher.dispatch()
    assert first_count == 2
    assert len(tui.delivered) == 2

    second_count = dispatcher.dispatch()
    assert second_count == 0  # nothing new delivered
    assert len(tui.delivered) == 2  # STILL 2 — no re-delivery


def test_dispatch_idempotent_with_new_notifier_added_later() -> None:
    """A second notifier added later receives notifications; the first does not re-deliver."""
    store = InMemoryNotificationStore()
    store.append([_n("N-001", "dk-1")])

    tui1 = TUINotifier()
    tui1.name = "tui1"  # type: ignore[assignment]
    dispatcher = NotificationDispatcher(notifiers=[tui1], store=store)
    dispatcher.dispatch()
    assert len(tui1.delivered) == 1

    # Add a second distinct notifier — it should receive the notification now
    tui2 = TUINotifier()
    tui2.name = "tui2"  # type: ignore[assignment]
    dispatcher2 = NotificationDispatcher(notifiers=[tui1, tui2], store=store)
    count = dispatcher2.dispatch()

    assert count == 1  # only tui2 delivered
    assert len(tui1.delivered) == 1  # tui1 did NOT re-deliver
    assert len(tui2.delivered) == 1


# ── supports() gate ───────────────────────────────────────────────────────────


def test_notifier_with_supports_false_is_skipped() -> None:
    store = InMemoryNotificationStore()
    store.append([_n("N-001", "dk-1")])

    never = _NeverNotifier()
    dispatcher = NotificationDispatcher(notifiers=[never], store=store)
    count = dispatcher.dispatch()

    assert count == 0
    # notification still pending since nothing delivered
    assert len(store.pending()) == 1


def test_mixed_notifiers_supports_gate() -> None:
    """Only notifiers whose supports() is True are called."""
    store = InMemoryNotificationStore()
    store.append([_n("N-001", "dk-1")])

    tui = TUINotifier()
    never = _NeverNotifier()
    dispatcher = NotificationDispatcher(notifiers=[never, tui], store=store)
    count = dispatcher.dispatch()

    assert count == 1
    assert len(tui.delivered) == 1


# ── empty store ───────────────────────────────────────────────────────────────


def test_dispatch_empty_store_returns_zero() -> None:
    store = InMemoryNotificationStore()
    tui = TUINotifier()
    dispatcher = NotificationDispatcher(notifiers=[tui], store=store)
    assert dispatcher.dispatch() == 0
    assert tui.delivered == []


# ── TUINotifier unit ──────────────────────────────────────────────────────────


def test_tui_notifier_supports_all() -> None:
    tui = TUINotifier()
    n = _n("N-001", "dk-1", kind="change")
    assert tui.supports(n) is True
    n2 = _n("N-002", "dk-2", kind="reminder")
    assert tui.supports(n2) is True


def test_tui_notifier_send_records_and_returns_delivered() -> None:
    tui = TUINotifier()
    n = _n("N-001", "dk-1")
    result = tui.send(n)
    assert result.delivered is True
    assert len(tui.delivered) == 1
    assert tui.delivered[0].id == "N-001"


@pytest.mark.parametrize("backend", ["memory"])
def test_tui_notifier_name(backend: str) -> None:
    tui = TUINotifier()
    assert tui.name == "tui"
