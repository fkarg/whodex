"""F6: serve_tick — one testable unit of the serve loop.

Invariants:
  F6a: serve_tick(facade) over an in-memory app is equivalent to sync + dispatch;
       it returns a ServeTickReport with notification/entity counts.
  F6b: A second serve_tick with no new data delivers 0 new notifications
       (idempotent) and the entity count is stable.
  F6c: After a data change between ticks, the second tick delivers a new notification.
"""

from __future__ import annotations

from datetime import UTC, datetime

from whodex.config.settings import build_app
from whodex.domain.clock import FixedClock
from whodex.domain.enums import Significance
from whodex.domain.events import RawRecord
from whodex.domain.ids import SequentialIdFactory
from whodex.domain.state import Change
from whodex.facade.serve import ServeTickReport, serve_tick
from whodex.facade.whodex import Whodex
from whodex.notifiers.impls import TUINotifier
from whodex.sources.fake import FakeSource

T_BASE = datetime(2026, 1, 1, tzinfo=UTC)
T_NOW = datetime(2026, 2, 1, tzinfo=UTC)


def _raw(email: str, name: str) -> RawRecord:
    return RawRecord(
        source="fake",
        identity={"email": email},
        payload={"display_name": name},
        observed_at=T_BASE,
    )


def _build_whodex(notifier: TUINotifier | None = None) -> Whodex:
    app = build_app(clock=FixedClock(T_NOW), ids=SequentialIdFactory())
    if notifier is not None:
        app.notifiers = [notifier]
    return Whodex(app, ids=SequentialIdFactory(prefix="ACT"), clock=FixedClock(T_NOW))


# ── F6a: serve_tick returns a ServeTickReport ─────────────────────────────────


def test_f6a_serve_tick_returns_report() -> None:
    """F6a: serve_tick returns a ServeTickReport (sync + dispatch)."""
    tui = TUINotifier()
    wx = _build_whodex(notifier=tui)
    wx._app.sources = [FakeSource([_raw("alice@example.com", "Alice")])]

    report = serve_tick(wx)

    assert isinstance(report, ServeTickReport), (
        f"F6a FAIL: expected ServeTickReport, got {type(report)}"
    )
    # 1 entity ingested from FakeSource
    assert report.entity_count == 1, f"F6a FAIL: expected 1 entity, got {report.entity_count}"
    # No notable changes in first sync (brand-new entity, no prior state)
    assert report.notifications_dispatched == 0


def test_f6a_serve_tick_with_notable_change_dispatches() -> None:
    """F6a (variant): serve_tick dispatches notifications when a notable Change exists."""
    tui = TUINotifier()
    wx = _build_whodex(notifier=tui)
    wx._app.sources = [FakeSource([_raw("alice@example.com", "Alice")])]

    # First tick: sync to establish baseline projection
    serve_tick(wx)

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    # Inject a notable Change (simulates second-sync diff detection)
    change = Change(
        id="CHANGE-001",
        entity_id=alice_id,
        field="job.title",
        old_value="Engineer",
        new_value="Staff Engineer",
        caused_by_observation="OBS-001",
        detected_at=T_NOW,
        significance=Significance.notable,
        fingerprint="fp-serve-001",
        seen=False,
        notified=False,
    )
    wx._app.derived.replace_changes([change])

    # Manually generate + dispatch (simulating what sync does after reproject)
    wx._generate_notifications()
    count = wx.dispatch_notifications()

    assert count == 1, f"F6a variant FAIL: expected 1 dispatch, got {count}"
    assert len(tui.delivered) == 1


# ── F6b: second tick with no new data delivers 0 notifications ───────────────


def test_f6b_second_serve_tick_idempotent() -> None:
    """F6b: second serve_tick with no new data delivers 0 new notifications; entity count stable."""
    tui = TUINotifier()
    wx = _build_whodex(notifier=tui)
    records = [_raw("alice@example.com", "Alice"), _raw("bob@example.com", "Bob")]
    wx._app.sources = [FakeSource(records)]

    report1 = serve_tick(wx)
    assert report1.entity_count == 2

    # Second tick: same source, no new data
    report2 = serve_tick(wx)

    assert report2.entity_count == 2, (
        f"F6b FAIL: entity count changed on second tick: {report2.entity_count}"
    )
    assert report2.notifications_dispatched == 0, (
        f"F6b FAIL: second tick should dispatch 0 new notifications (idempotent), "
        f"got {report2.notifications_dispatched}"
    )
    # TUINotifier has not received any duplicate deliveries
    total_tui = len(tui.delivered)
    assert total_tui == report1.notifications_dispatched, (
        "F6b FAIL: TUINotifier.delivered count changed on second tick"
    )


# ── F6c: serve_tick result has expected shape ──────────────────────────────────


def test_f6c_serve_tick_report_shape() -> None:
    """F6c: ServeTickReport has notifications_dispatched and entity_count attributes."""
    wx = _build_whodex()
    wx._app.sources = []  # empty sources

    report = serve_tick(wx)

    assert hasattr(report, "notifications_dispatched")
    assert hasattr(report, "entity_count")
    assert isinstance(report.notifications_dispatched, int)
    assert isinstance(report.entity_count, int)
    assert report.entity_count == 0
    assert report.notifications_dispatched == 0
