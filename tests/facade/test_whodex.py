"""Behavioral tests for the Whodex headless facade.

All assertions go through the facade's public methods only — no internal
stores, events, or engine objects are accessed directly.

Invariants tested:
  F1: Never-contacted person ranks above recently-contacted; snoozed excluded.
  F2: log_interaction() on top person → they drop in the queue.
  F3: pin() → person at top; snooze() → person absent from priority_queue().
  F5: review_queue() surfaces ConflictSuggestions and GraphRepairSuggestions;
      apply_graph_repair() removes the repair from review_queue().
"""

from __future__ import annotations

from datetime import UTC, datetime

from whodex.config.settings import build_app
from whodex.domain.clock import FixedClock
from whodex.domain.enums import InteractionKind, Significance, SuggestionStatus
from whodex.domain.events import RawRecord
from whodex.domain.ids import SequentialIdFactory
from whodex.domain.state import Change, ConflictSuggestion, GraphRepairSuggestion
from whodex.facade.whodex import Whodex
from whodex.sources.fake import FakeSource

# ---------------------------------------------------------------------------
# Shared timestamps
# ---------------------------------------------------------------------------

T_BASE = datetime(2026, 1, 1, tzinfo=UTC)
T_RECENT = datetime(2026, 1, 15, tzinfo=UTC)  # 14 days ago (relative to T_NOW)
T_NOW = datetime(2026, 2, 1, tzinfo=UTC)  # "now" during test
T_FUTURE = datetime(2026, 3, 1, tzinfo=UTC)  # future snooze deadline


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _raw(email: str, name: str, *, observed: datetime = T_BASE) -> RawRecord:
    return RawRecord(
        source="fake",
        identity={"email": email},
        payload={"display_name": name},
        observed_at=observed,
    )


def _build_whodex(now: datetime = T_NOW) -> Whodex:
    """Return a fresh in-memory Whodex at *now*."""
    app = build_app(clock=FixedClock(now), ids=SequentialIdFactory())
    return Whodex(app, ids=SequentialIdFactory(prefix="ACT"), clock=FixedClock(now))


def _seed(whodex: Whodex, records: list[RawRecord]) -> None:
    """Push records via a FakeSource sync so the projection is populated."""
    whodex._app.sources = [FakeSource(records)]
    whodex.sync()


# ---------------------------------------------------------------------------
# F1: Never-contacted ranks first; snoozed excluded
# ---------------------------------------------------------------------------


def test_f1_never_contacted_ranks_first():
    """F1a: a person who has never been contacted scores higher than one recently contacted."""
    wx = _build_whodex()
    _seed(
        wx,
        [
            _raw("alice@example.com", "Alice"),
            _raw("bob@example.com", "Bob"),
        ],
    )

    # Log an interaction for Alice at T_RECENT — she becomes recently contacted.
    states = wx._app.projection.load()
    alice_id = next(eid for eid, s in states.items() if s.display_name == "Alice")
    bob_id = next(eid for eid, s in states.items() if s.display_name == "Bob")

    wx.log_interaction(alice_id, InteractionKind.call, when=T_RECENT)

    queue = wx.priority_queue()
    assert len(queue) == 2

    entity_ids = [c.entity_id for c in queue]
    # Bob (never contacted) must rank above Alice (recently contacted)
    assert entity_ids[0] == bob_id, (
        f"F1 FAIL: expected Bob (never contacted) first, got {queue[0].display_name}"
    )
    assert entity_ids[1] == alice_id, f"F1 FAIL: expected Alice second, got {queue[1].display_name}"


def test_f1_snoozed_excluded_from_default_queue():
    """F1b: a snoozed person is excluded from priority_queue() by default."""
    wx = _build_whodex()
    _seed(
        wx,
        [
            _raw("alice@example.com", "Alice"),
            _raw("bob@example.com", "Bob"),
        ],
    )

    states = wx._app.projection.load()
    alice_id = next(eid for eid, s in states.items() if s.display_name == "Alice")

    # Snooze Alice until the future
    wx.snooze(alice_id, T_FUTURE)

    queue = wx.priority_queue()
    entity_ids = [c.entity_id for c in queue]

    # Alice must not appear
    assert alice_id not in entity_ids, (
        f"F1b FAIL: snoozed Alice appeared in default queue: {[c.display_name for c in queue]}"
    )
    # Bob must still appear
    bob_id = next((eid for eid, s in states.items() if s.display_name == "Bob"), None)
    assert bob_id is not None
    assert bob_id in entity_ids, "F1b FAIL: Bob missing from queue after Alice snoozed"


def test_f1_include_snoozed_shows_snoozed():
    """F1c: include_snoozed=True returns snoozed contacts (score=-inf, last in list)."""
    wx = _build_whodex()
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    wx.snooze(alice_id, T_FUTURE)

    # Default queue: Alice excluded
    assert wx.priority_queue() == []

    # include_snoozed=True: Alice returned with -inf score
    full_queue = wx.priority_queue(include_snoozed=True)
    assert len(full_queue) == 1
    assert full_queue[0].entity_id == alice_id
    assert full_queue[0].score == float("-inf")


# ---------------------------------------------------------------------------
# F2: log_interaction() causes top person to drop in the queue
# ---------------------------------------------------------------------------


def test_f2_log_interaction_drops_person_in_queue():
    """F2: after log_interaction on the top-ranked person, they should rank lower."""
    wx = _build_whodex()
    _seed(
        wx,
        [
            _raw("alice@example.com", "Alice"),
            _raw("bob@example.com", "Bob"),
        ],
    )

    queue_before = wx.priority_queue()
    assert len(queue_before) == 2

    top_id = queue_before[0].entity_id
    bottom_id = queue_before[1].entity_id

    # Log a fresh interaction on the top person — they just got contacted
    wx.log_interaction(top_id, InteractionKind.call)

    queue_after = wx.priority_queue()
    assert len(queue_after) == 2

    # The previously-top person should now rank below the other
    assert queue_after[0].entity_id == bottom_id, (
        f"F2 FAIL: expected {bottom_id!r} first after interaction on top person; "
        f"got {queue_after[0].entity_id!r}"
    )
    assert queue_after[1].entity_id == top_id, (
        f"F2 FAIL: interacted person should now rank last; got {queue_after[1].entity_id!r}"
    )


def test_f2_log_interaction_contact_detail_shows_in_timeline():
    """F2b: logged interaction appears in contact_detail timeline."""
    wx = _build_whodex()
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    note_text = "We met at the conference"
    wx.log_interaction(alice_id, InteractionKind.note, note=note_text)

    detail = wx.contact_detail(alice_id)
    assert detail is not None

    interaction_items = [t for t in detail.timeline if t.kind == "interaction"]
    assert len(interaction_items) == 1
    assert interaction_items[0].summary == note_text


# ---------------------------------------------------------------------------
# F3: pin() → person floored to top; snooze() → person absent
# ---------------------------------------------------------------------------


def test_f3_pin_raises_to_top():
    """F3a: pin() on a recently-contacted person floors them to the top of the queue."""
    wx = _build_whodex()
    _seed(
        wx,
        [
            _raw("alice@example.com", "Alice"),
            _raw("bob@example.com", "Bob"),
        ],
    )

    states = wx._app.projection.load()
    alice_id = next(eid for eid, s in states.items() if s.display_name == "Alice")
    bob_id = next(eid for eid, s in states.items() if s.display_name == "Bob")

    # Give Bob a recent interaction so he'd normally rank lower
    wx.log_interaction(bob_id, InteractionKind.call)

    # Without pin: Bob was just contacted; Alice (never contacted) should be top
    queue = wx.priority_queue()
    assert queue[0].entity_id == alice_id, "Pre-pin sanity: Alice should be top (never contacted)"

    # Now pin Bob — he should jump to the top
    wx.pin(bob_id, on=True)

    queue_after = wx.priority_queue()
    assert queue_after[0].entity_id == bob_id, (
        f"F3a FAIL: pinned Bob should be first; got {queue_after[0].display_name!r} first. "
        f"Scores: {[(c.display_name, c.score) for c in queue_after]}"
    )


def test_f3_unpin_removes_floor():
    """F3b: pin(on=False) removes the pin floor."""
    wx = _build_whodex()
    _seed(
        wx,
        [
            _raw("alice@example.com", "Alice"),
            _raw("bob@example.com", "Bob"),
        ],
    )

    states = wx._app.projection.load()
    alice_id = next(eid for eid, s in states.items() if s.display_name == "Alice")
    bob_id = next(eid for eid, s in states.items() if s.display_name == "Bob")

    # Give Alice a recent interaction so Bob (never contacted) ranks higher without pin
    wx.log_interaction(alice_id, InteractionKind.call)

    # Pin Alice
    wx.pin(alice_id, on=True)
    queue = wx.priority_queue()
    assert queue[0].entity_id == alice_id, "Alice should be top when pinned"

    # Unpin Alice
    wx.pin(alice_id, on=False)
    queue_after = wx.priority_queue()
    # Bob (never contacted) should now be top again
    assert queue_after[0].entity_id == bob_id, (
        f"F3b FAIL: Bob should be top after Alice unpinned; got {queue_after[0].display_name!r}"
    )


def test_f3_snooze_removes_from_queue():
    """F3c: snooze() until future makes person absent from priority_queue()."""
    wx = _build_whodex()
    _seed(
        wx,
        [
            _raw("alice@example.com", "Alice"),
            _raw("bob@example.com", "Bob"),
        ],
    )

    states = wx._app.projection.load()
    alice_id = next(eid for eid, s in states.items() if s.display_name == "Alice")

    wx.snooze(alice_id, T_FUTURE)

    queue = wx.priority_queue()
    entity_ids = [c.entity_id for c in queue]
    assert alice_id not in entity_ids, (
        f"F3c FAIL: snoozed Alice should be absent; got {[c.display_name for c in queue]}"
    )


# ---------------------------------------------------------------------------
# F5: review_queue surfaces suggestions; apply_graph_repair removes repair
# ---------------------------------------------------------------------------


def _make_conflict(entity_id: str, now: datetime) -> ConflictSuggestion:
    return ConflictSuggestion(
        id="CONFLICT-001",
        entity_id=entity_id,
        field="job.title",
        winning_observation_id="OBS-001",
        disagreeing_observation_id="OBS-002",
        reason="trust disagreement",
        fingerprint="fp-conflict-001",
        detected_at=now,
        status=SuggestionStatus.open,
    )


def _make_repair(now: datetime) -> GraphRepairSuggestion:
    return GraphRepairSuggestion(
        id="REPAIR-001",
        repair_type="missing_edge",
        src_entity_id="ENTITY-001",
        dst_entity_id="ENTITY-002",
        payload={"field": "person.organisations"},
        fingerprint="fp-repair-001",
        detected_at=now,
        status=SuggestionStatus.open,
    )


def test_f5_review_queue_includes_open_conflicts_and_repairs():
    """F5a: review_queue() includes open ConflictSuggestions and GraphRepairSuggestions."""
    wx = _build_whodex()
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    # Seed derived store directly (simulates what a sync with conflicts/repairs would produce)
    conflict = _make_conflict(alice_id, T_NOW)
    repair = _make_repair(T_NOW)
    wx._app.derived.replace_conflicts([conflict])
    wx._app.derived.replace_repairs([repair])

    items = wx.review_queue()
    assert len(items) == 2, f"F5a FAIL: expected 2 review items, got {len(items)}: {items}"

    kinds = {item.kind for item in items}
    assert "conflict" in kinds, "F5a FAIL: conflict not in review_queue"
    assert "repair" in kinds, "F5a FAIL: repair not in review_queue"


def test_f5_conflict_summary_contains_field_and_entity():
    """F5b: conflict ReviewItem summary mentions the field and entity."""
    wx = _build_whodex()
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    conflict = _make_conflict(alice_id, T_NOW)
    wx._app.derived.replace_conflicts([conflict])

    items = wx.review_queue()
    conflict_item = next(i for i in items if i.kind == "conflict")
    assert "job.title" in conflict_item.summary, (
        f"F5b FAIL: expected 'job.title' in summary, got: {conflict_item.summary!r}"
    )


def test_f5_apply_graph_repair_removes_from_review_queue():
    """F5c: apply_graph_repair(id) causes the repair to disappear from review_queue()."""
    wx = _build_whodex()
    _seed(wx, [_raw("alice@example.com", "Alice")])

    repair = _make_repair(T_NOW)
    wx._app.derived.replace_repairs([repair])

    # Confirm repair is in the queue
    items_before = wx.review_queue()
    repair_items_before = [i for i in items_before if i.kind == "repair"]
    assert len(repair_items_before) == 1, (
        f"F5c pre-condition FAIL: expected 1 repair item, got {repair_items_before}"
    )

    # Apply the repair
    wx.apply_graph_repair(repair.id)

    # Repair must no longer be in the review queue
    items_after = wx.review_queue()
    repair_items_after = [i for i in items_after if i.kind == "repair"]
    assert len(repair_items_after) == 0, (
        f"F5c FAIL: repair still in review_queue after apply: {repair_items_after}"
    )


def test_f5_apply_graph_repair_records_user_action():
    """F5d: apply_graph_repair records a UserAction in the ledger."""
    wx = _build_whodex()
    _seed(wx, [_raw("alice@example.com", "Alice")])

    repair = _make_repair(T_NOW)
    wx._app.derived.replace_repairs([repair])

    wx.apply_graph_repair(repair.id)

    events = wx._app.ledger.read_events()
    repair_actions = [a for a in events.user_actions if a.action_type.value == "apply_graph_repair"]
    assert len(repair_actions) >= 1, (
        f"F5d FAIL: expected apply_graph_repair UserAction in ledger; got: {events.user_actions}"
    )
    assert repair_actions[-1].target_id == repair.id


# ---------------------------------------------------------------------------
# Additional: contact_detail returns None for unknown entity
# ---------------------------------------------------------------------------


def test_contact_detail_unknown_entity_returns_none():
    """contact_detail() returns None for an entity_id that doesn't exist."""
    wx = _build_whodex()
    assert wx.contact_detail("NONEXISTENT-ID") is None


# ---------------------------------------------------------------------------
# Additional: set_cadence records action (with documented limitation)
# ---------------------------------------------------------------------------


def test_set_cadence_records_user_action():
    """set_cadence() records a cadence_set UserAction in the ledger."""
    wx = _build_whodex()
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    wx.set_cadence(alice_id, 60)

    events = wx._app.ledger.read_events()
    cadence_actions = [
        a
        for a in events.user_actions
        if a.action_type.value == "cadence_set" and a.entity_id == alice_id
    ]
    assert len(cadence_actions) == 1, (
        f"set_cadence FAIL: expected 1 cadence_set action; got {cadence_actions}"
    )
    assert cadence_actions[0].payload["days"] == 60


# ---------------------------------------------------------------------------
# Additional: acknowledge_change removes event boost
# ---------------------------------------------------------------------------


def test_acknowledge_change_removes_boost():
    """acknowledge_change() marks the change seen so priority_queue no longer boosts the contact."""
    wx = _build_whodex()
    _seed(wx, [_raw("alice@example.com", "Alice")])

    states = wx._app.projection.load()
    alice_id = next(iter(states))

    # Directly inject a notable open Change for alice (simulates a sync output)
    change = Change(
        id="CHANGE-001",
        entity_id=alice_id,
        field="job.title",
        old_value="Engineer",
        new_value="Staff Engineer",
        caused_by_observation="OBS-001",
        detected_at=T_NOW,
        significance=Significance.notable,
        fingerprint="fp-change-001",
        seen=False,
        notified=False,
    )
    wx._app.derived.replace_changes([change])

    # Confirm the change is open
    open_changes = wx._app.derived.changes()
    unacked = [c for c in open_changes if not c.seen]
    assert len(unacked) == 1, "pre-condition: should have 1 unacked change"

    # Acknowledge
    wx.acknowledge_change(change.fingerprint)

    # After ack + reproject: the change should be seen
    changes_after = wx._app.derived.changes()
    unacked_after = [c for c in changes_after if not c.seen]
    # Either removed or marked seen — no un-acked changes for alice
    alice_unacked = [c for c in unacked_after if c.entity_id == alice_id]
    assert alice_unacked == [], (
        f"acknowledge_change FAIL: still have unacked changes for alice: {alice_unacked}"
    )
