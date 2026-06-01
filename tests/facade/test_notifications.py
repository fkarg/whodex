"""F4: generate Notifications from sync and dispatch them via TUINotifier.

Invariants:
  F4a: A notable Change (Significance.notable) from a sync produces a Notification
       that the TUINotifier receives after dispatch_notifications().
  F4b: Dispatching again does NOT re-deliver the same notification (idempotent).
  F4c: A trivial/minor Change does NOT produce a notification.
  F4d: An already-seen (acked) Change does NOT produce a notification.
"""

from __future__ import annotations

from datetime import UTC, datetime

from whodex.config.settings import build_app
from whodex.domain.clock import FixedClock
from whodex.domain.enums import Significance
from whodex.domain.events import RawRecord
from whodex.domain.ids import SequentialIdFactory
from whodex.domain.state import Change
from whodex.facade.whodex import Whodex
from whodex.notifiers.impls import TUINotifier
from whodex.sources.fake import FakeSource

T_BASE = datetime(2026, 1, 1, tzinfo=UTC)
T_NOW = datetime(2026, 2, 1, tzinfo=UTC)


def _raw(email: str, name: str, title: str | None = None) -> RawRecord:
    payload: dict = {"display_name": name}
    if title is not None:
        payload["title"] = title
    return RawRecord(
        source="fake",
        identity={"email": email},
        payload=payload,
        observed_at=T_BASE,
    )


def _build_whodex(notifier: TUINotifier | None = None) -> Whodex:
    app = build_app(clock=FixedClock(T_NOW), ids=SequentialIdFactory())
    if notifier is not None:
        app.notifiers = [notifier]
    return Whodex(app, ids=SequentialIdFactory(prefix="ACT"), clock=FixedClock(T_NOW))


def _seed(wx: Whodex, records: list[RawRecord]) -> None:
    wx._app.sources = [FakeSource(records)]
    wx.sync()


def _notable_change(entity_id: str) -> Change:
    return Change(
        id="CHANGE-001",
        entity_id=entity_id,
        field="job.title",
        old_value="Engineer",
        new_value="Staff Engineer",
        caused_by_observation="OBS-001",
        detected_at=T_NOW,
        significance=Significance.notable,
        fingerprint="fp-notable-001",
        seen=False,
        notified=False,
    )


def _minor_change(entity_id: str) -> Change:
    return Change(
        id="CHANGE-002",
        entity_id=entity_id,
        field="job.title",
        old_value="Engineer",
        new_value="Senior Engineer",
        caused_by_observation="OBS-002",
        detected_at=T_NOW,
        significance=Significance.minor,
        fingerprint="fp-minor-001",
        seen=False,
        notified=False,
    )


# ── F4a: notable Change → TUINotifier receives it ────────────────────────────


def test_f4a_notable_change_produces_notification() -> None:
    """F4a: after sync with a notable Change seeded, dispatch delivers to TUINotifier."""
    tui = TUINotifier()
    wx = _build_whodex(notifier=tui)
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    # Seed a notable Change into derived store (simulates projection output)
    change = _notable_change(alice_id)
    wx._app.derived.replace_changes([change])

    # Generate notifications from changes + dispatch
    wx._generate_notifications()
    delivered = wx.dispatch_notifications()

    assert delivered >= 1, f"F4a FAIL: expected at least 1 delivery, got {delivered}"
    assert len(tui.delivered) >= 1, "F4a FAIL: TUINotifier received no notifications"
    kinds = {n.kind for n in tui.delivered}
    assert "change" in kinds, f"F4a FAIL: expected 'change' kind, got {kinds}"
    entity_ids = {n.entity_id for n in tui.delivered}
    assert alice_id in entity_ids, f"F4a FAIL: expected alice_id in notifications, got {entity_ids}"


# ── F4b: dispatch twice → not re-delivered ───────────────────────────────────


def test_f4b_dispatch_notifications_idempotent() -> None:
    """F4b: calling dispatch_notifications() twice delivers each notification at most once."""
    tui = TUINotifier()
    wx = _build_whodex(notifier=tui)
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    change = _notable_change(alice_id)
    wx._app.derived.replace_changes([change])

    wx._generate_notifications()

    first = wx.dispatch_notifications()
    assert first >= 1

    second = wx.dispatch_notifications()
    assert second == 0, f"F4b FAIL: second dispatch should deliver 0 (idempotent), got {second}"

    # TUINotifier.delivered list stays the same length (no re-delivery)
    assert len(tui.delivered) == first, (
        f"F4b FAIL: TUINotifier.delivered grew on re-dispatch: {len(tui.delivered)} != {first}"
    )


# ── F4c: trivial/minor Change does NOT produce a notification ─────────────────


def test_f4c_minor_change_produces_no_notification() -> None:
    """F4c: a Change with Significance.minor does not become a Notification."""
    tui = TUINotifier()
    wx = _build_whodex(notifier=tui)
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    # Only seed a MINOR change — no notable ones
    change = _minor_change(alice_id)
    wx._app.derived.replace_changes([change])

    wx._generate_notifications()
    delivered = wx.dispatch_notifications()

    assert delivered == 0, f"F4c FAIL: minor change should produce 0 deliveries, got {delivered}"
    assert tui.delivered == [], (
        f"F4c FAIL: TUINotifier should have received nothing, got {tui.delivered}"
    )


# ── F4d: already-seen (acked) notable Change produces no notification ─────────


def test_f4d_acked_change_produces_no_notification() -> None:
    """F4d: a notable Change that is already seen=True does not produce a notification."""
    tui = TUINotifier()
    wx = _build_whodex(notifier=tui)
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    # Notable but already seen
    change = Change(
        id="CHANGE-003",
        entity_id=alice_id,
        field="job.title",
        old_value="Engineer",
        new_value="Director",
        caused_by_observation="OBS-003",
        detected_at=T_NOW,
        significance=Significance.notable,
        fingerprint="fp-acked-001",
        seen=True,  # already acked
        notified=False,
    )
    wx._app.derived.replace_changes([change])

    wx._generate_notifications()
    delivered = wx.dispatch_notifications()

    assert delivered == 0, (
        f"F4d FAIL: already-seen notable change should produce 0 deliveries, got {delivered}"
    )


# ── F4e: sync + two-pass scenario (dedupe across syncs) ──────────────────────


def test_f4e_notification_deduped_across_generate_calls() -> None:
    """F4e: _generate_notifications() x2 for the same change adds only one notification."""
    tui = TUINotifier()
    wx = _build_whodex(notifier=tui)
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    change = _notable_change(alice_id)
    wx._app.derived.replace_changes([change])

    # Generate twice (simulates two syncs over the same un-acked change)
    wx._generate_notifications()
    wx._generate_notifications()

    delivered = wx.dispatch_notifications()

    assert delivered == 1, f"F4e FAIL: expected exactly 1 delivery (dedupe), got {delivered}"
    assert len(tui.delivered) == 1, (
        f"F4e FAIL: TUINotifier should have received 1 notification, got {len(tui.delivered)}"
    )
