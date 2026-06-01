"""Phase-1g end-to-end acceptance invariants.

Tests exercise real behavior through the FACADE (not the UI).
No internals (stores, engines) are accessed directly unless
required to set up state (e.g. seed sources).

Invariants
----------
G1  sync() + priority_queue() ranks vault people with why-now reasons.
G2  log_interaction(top_person) causes that person to drop from top of queue.
G3  pin(someone) → floored to top; snooze(someone, future) → absent from
    priority_queue().
G4  pending_notifications() / dispatch_notifications() delivers once;
    second dispatch delivers 0 (idempotent).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from whodex.config.settings import build_app
from whodex.domain.clock import FixedClock
from whodex.domain.enums import InteractionKind, Significance
from whodex.domain.events import RawRecord
from whodex.domain.ids import SequentialIdFactory
from whodex.domain.state import Change
from whodex.facade.whodex import Whodex
from whodex.notifiers.impls import TUINotifier
from whodex.sources.fake import FakeSource

# ---------------------------------------------------------------------------
# Shared timestamps
# ---------------------------------------------------------------------------

T_BASE = datetime(2026, 1, 1, tzinfo=UTC)
T_NOW = datetime(2026, 2, 1, tzinfo=UTC)
T_FUTURE = T_NOW + timedelta(days=30)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw(email: str, name: str, *, observed: datetime = T_BASE) -> RawRecord:
    return RawRecord(
        source="fake",
        identity={"email": email},
        payload={"display_name": name},
        observed_at=observed,
    )


def _make_vault(tmp_path: Path) -> Path:
    """Create a minimal Obsidian vault with two People notes."""
    vault = tmp_path / "vault"
    (vault / "People").mkdir(parents=True)

    (vault / "People" / "Alice Vault.md").write_text(
        "---\n"
        "type: Person\n"
        "tags:\n"
        "  - Person\n"
        "emails:\n"
        "  - alice@example.com\n"
        "---\n\n"
        "## Notes\n"
        "- Alice from vault.\n"
    )
    (vault / "People" / "Bob Vault.md").write_text(
        "---\n"
        "type: Person\n"
        "tags:\n"
        "  - Person\n"
        "emails:\n"
        "  - bob@example.com\n"
        "---\n\n"
        "## Notes\n"
        "- Bob from vault.\n"
    )
    return vault


def _build_whodex_with_fake(
    notifier: TUINotifier | None = None,
    now: datetime = T_NOW,
) -> tuple[Whodex, list[str]]:
    """Build a Whodex backed by FakeSource with two contacts.

    Returns (facade, [alice_id, bob_id]) after an initial sync.
    """
    app = build_app(clock=FixedClock(now), ids=SequentialIdFactory())
    if notifier is not None:
        app.notifiers = [notifier]
    wx = Whodex(app, ids=SequentialIdFactory(prefix="ACT"), clock=FixedClock(now))

    app.sources = [
        FakeSource(
            [
                _raw("alice@example.com", "Alice"),
                _raw("bob@example.com", "Bob"),
            ]
        )
    ]
    wx.sync()

    states = app.projection.load()
    alice_id = next(eid for eid, s in states.items() if s.display_name == "Alice")
    bob_id = next(eid for eid, s in states.items() if s.display_name == "Bob")
    return wx, [alice_id, bob_id]


# ---------------------------------------------------------------------------
# G1: sync + priority_queue ranks people with why-now
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_g1_sync_and_priority_queue_via_vault(tmp_path: Path) -> None:
    """G1: After sync over a vault, priority_queue() returns both people with why-now.

    Uses a real vault (Obsidian source) over a tmp SQLite db.
    """
    vault = _make_vault(tmp_path)
    db = tmp_path / "whodex.db"
    app = build_app(vault=vault, db=db, clock=FixedClock(T_NOW))
    wx = Whodex(app, clock=FixedClock(T_NOW))

    wx.sync()

    queue = wx.priority_queue()
    assert len(queue) == 2, f"G1 FAIL: expected 2 contacts, got {len(queue)}"

    # All contacts must have why-now reasons (queue engine always sets reasons)
    for contact in queue:
        assert isinstance(contact.why, list), (
            f"G1 FAIL: why must be a list, got {contact.why!r} for {contact.display_name}"
        )
        assert contact.score != float("-inf"), (
            f"G1 FAIL: score must be finite for unsnoozed contact {contact.display_name}"
        )

    # Contacts must be ranked: highest score first
    scores = [c.score for c in queue]
    assert scores == sorted(scores, reverse=True), (
        f"G1 FAIL: queue must be sorted descending by score, got {scores}"
    )


@pytest.mark.e2e
def test_g1_sync_and_priority_queue_via_fake_source() -> None:
    """G1 (FakeSource variant): sync + priority_queue over two contacts returns both ranked."""
    wx, (alice_id, bob_id) = _build_whodex_with_fake()

    queue = wx.priority_queue()
    assert len(queue) == 2, f"G1 FAIL: expected 2 contacts in queue, got {len(queue)}"

    entity_ids = {c.entity_id for c in queue}
    assert alice_id in entity_ids, "G1 FAIL: Alice missing from priority_queue"
    assert bob_id in entity_ids, "G1 FAIL: Bob missing from priority_queue"

    # Scores are finite (not snoozed)
    for contact in queue:
        assert contact.score != float("-inf"), (
            f"G1 FAIL: {contact.display_name} has -inf score (unexpectedly snoozed)"
        )


# ---------------------------------------------------------------------------
# G2: log_interaction(top_person) → they drop from top (overdue reset)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_g2_log_interaction_drops_top_person() -> None:
    """G2: After log_interaction on the top-ranked person, they drop below the other.

    This validates the "overdue reset" behavior: a freshly-contacted person
    has lower urgency than one who has never been contacted.
    """
    wx, (alice_id, bob_id) = _build_whodex_with_fake()

    queue_before = wx.priority_queue()
    assert len(queue_before) == 2, "G2 pre-condition: need 2 contacts"

    top_id = queue_before[0].entity_id
    bottom_id = queue_before[1].entity_id

    # Log interaction on the top person — they get "just contacted" signal
    wx.log_interaction(top_id, InteractionKind.call)

    queue_after = wx.priority_queue()
    assert len(queue_after) == 2

    # The previously-top person must now rank lower
    assert queue_after[0].entity_id == bottom_id, (
        f"G2 FAIL: expected {bottom_id!r} to be top after interaction on {top_id!r}; "
        f"got {queue_after[0].entity_id!r} first. "
        f"Scores after: {[(c.display_name, c.score) for c in queue_after]}"
    )
    assert queue_after[1].entity_id == top_id, (
        f"G2 FAIL: interacted person {top_id!r} should now rank last"
    )


@pytest.mark.e2e
def test_g2_log_interaction_with_note_appears_in_timeline() -> None:
    """G2b: logged interaction with a note appears in contact_detail timeline."""
    wx, (alice_id, _bob_id) = _build_whodex_with_fake()

    note_text = "Caught up at Phase 1g launch party"
    wx.log_interaction(alice_id, InteractionKind.note, note=note_text)

    detail = wx.contact_detail(alice_id)
    assert detail is not None

    interaction_items = [t for t in detail.timeline if t.kind == "interaction"]
    assert len(interaction_items) >= 1, "G2b FAIL: no interaction in timeline"
    summaries = [t.summary for t in interaction_items]
    assert note_text in summaries, (
        f"G2b FAIL: note {note_text!r} not found in timeline summaries: {summaries}"
    )


# ---------------------------------------------------------------------------
# G3: pin → floored to top; snooze → absent from priority_queue
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_g3_pin_floored_to_top() -> None:
    """G3a: pin(someone) floors them to top of priority_queue regardless of recency."""
    wx, (alice_id, bob_id) = _build_whodex_with_fake()

    # Log interaction for Bob to make Alice the natural top (never contacted)
    wx.log_interaction(bob_id, InteractionKind.call)

    queue_before = wx.priority_queue()
    assert queue_before[0].entity_id == alice_id, (
        "G3a pre-condition: Alice (never contacted) should be top"
    )

    # Pin Bob — he must jump to the top
    wx.pin(bob_id, on=True)

    queue_after = wx.priority_queue()
    assert queue_after[0].entity_id == bob_id, (
        f"G3a FAIL: pinned Bob should be top; got {queue_after[0].display_name!r} first. "
        f"Scores: {[(c.display_name, c.score) for c in queue_after]}"
    )


@pytest.mark.e2e
def test_g3_snooze_absent_from_priority_queue() -> None:
    """G3b: snooze(someone, future) causes them to be absent from priority_queue()."""
    wx, (alice_id, bob_id) = _build_whodex_with_fake()

    wx.snooze(alice_id, T_FUTURE)

    queue = wx.priority_queue()
    entity_ids = [c.entity_id for c in queue]
    names = [c.display_name for c in queue]
    assert alice_id not in entity_ids, (
        f"G3b FAIL: snoozed Alice should be absent from queue; got {names}"
    )
    assert bob_id in entity_ids, "G3b FAIL: Bob should still be in queue"


@pytest.mark.e2e
def test_g3_snooze_appears_with_include_snoozed() -> None:
    """G3c: snoozed contact appears with include_snoozed=True at score=-inf."""
    wx, (alice_id, _bob_id) = _build_whodex_with_fake()

    wx.snooze(alice_id, T_FUTURE)

    # Default: Alice excluded
    queue_default = wx.priority_queue()
    assert alice_id not in [c.entity_id for c in queue_default]

    # With include_snoozed: Alice present with -inf score
    queue_full = wx.priority_queue(include_snoozed=True)
    alice_items = [c for c in queue_full if c.entity_id == alice_id]
    assert len(alice_items) == 1, "G3c FAIL: Alice not in include_snoozed queue"
    assert alice_items[0].score == float("-inf"), (
        f"G3c FAIL: snoozed Alice must have -inf score, got {alice_items[0].score}"
    )


# ---------------------------------------------------------------------------
# G4: dispatch_notifications delivers once; second dispatch delivers 0
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_g4_dispatch_notifications_idempotent() -> None:
    """G4: dispatch_notifications() delivers once; second call delivers 0 (idempotent)."""
    tui = TUINotifier()
    wx, (alice_id, _bob_id) = _build_whodex_with_fake(notifier=tui)

    # Seed a notable Change to trigger a notification on next _generate_notifications call
    notable_change = Change(
        id="CHANGE-G4-001",
        entity_id=alice_id,
        field="job.title",
        old_value="Engineer",
        new_value="Staff Engineer",
        caused_by_observation="OBS-G4-001",
        detected_at=T_NOW,
        significance=Significance.notable,
        fingerprint="fp-g4-change-001",
        seen=False,
        notified=False,
    )
    wx._app.derived.replace_changes([notable_change])

    # Generate notifications from the notable change
    wx._generate_notifications()

    # First dispatch: should deliver at least 1
    first = wx.dispatch_notifications()
    assert first >= 1, f"G4 FAIL: first dispatch should deliver >= 1, got {first}"

    # Second dispatch: must be idempotent — 0 additional deliveries
    second = wx.dispatch_notifications()
    assert second == 0, f"G4 FAIL: second dispatch must deliver 0 (idempotent), got {second}"

    # TUINotifier received exactly first delivery (no re-delivery)
    assert len(tui.delivered) == first, (
        f"G4 FAIL: TUINotifier.delivered must be {first}, got {len(tui.delivered)}"
    )


@pytest.mark.e2e
def test_g4_sync_then_dispatch_then_dispatch_again() -> None:
    """G4b: Full sync → dispatch → dispatch again; second dispatch always returns 0."""
    tui = TUINotifier()
    app = build_app(clock=FixedClock(T_NOW), ids=SequentialIdFactory())
    app.notifiers = [tui]
    wx = Whodex(app, ids=SequentialIdFactory(prefix="ACT"), clock=FixedClock(T_NOW))
    app.sources = [FakeSource([_raw("alice@example.com", "Alice")])]

    # First sync — seeds any notifications from notable changes
    wx.sync()

    # Dispatch once (result may be 0 if no notable changes; that is fine)
    wx.dispatch_notifications()

    # Sync again (same data — no new changes expected)
    wx.sync()

    # Dispatch again — must be 0 (all already delivered or nothing to deliver)
    second = wx.dispatch_notifications()
    assert second == 0, (
        f"G4b FAIL: after re-sync, second dispatch should deliver 0 (idempotent), got {second}"
    )
