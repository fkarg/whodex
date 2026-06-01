"""Tests for new TUI screens: ReviewScreen, ContactPointsScreen, LogInteractionModal.

Thin behavioural layer only — uses Pilot + spy facade, no business logic.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from whodex.facade.dto import ContactDetail, RankedContact, ReviewItem
from whodex.tui.app import WhodexTUI

# ---------------------------------------------------------------------------
# Spy facade
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


class SpyFacade:
    """FacadeLike spy for testing new TUI screens."""

    def __init__(
        self,
        review_items: list[ReviewItem] | None = None,
        people: list[RankedContact] | None = None,
    ) -> None:
        self.log_calls: list[tuple[str, str, str | None]] = []
        self.apply_repair_calls: list[str] = []
        self.ack_calls: list[str] = []
        self.people_at_calls: list[str] = []
        self.pin_calls: list[tuple[str, bool]] = []
        self.snooze_calls: list[tuple[str, datetime]] = []
        self.detail_calls: list[str] = []
        self.review_queue_calls: int = 0

        self._review_items: list[ReviewItem] = review_items or []
        self._people: list[RankedContact] = people or []

        self._queue = [
            RankedContact(
                entity_id="e-alice",
                display_name="Alice",
                score=10.0,
                why=["overdue"],
                tier="A",
                last_interaction_at=_T0,
            ),
        ]

    def priority_queue(
        self, limit: int = 50, *, include_snoozed: bool = False
    ) -> list[RankedContact]:
        return self._queue

    def contact_detail(self, entity_id: str) -> ContactDetail | None:
        self.detail_calls.append(entity_id)
        return ContactDetail(
            entity_id=entity_id,
            display_name="Alice",
            kind="person",
        )

    def log_interaction(
        self,
        entity_id: str,
        kind: str = "note",
        *,
        note: str | None = None,
    ) -> None:
        self.log_calls.append((entity_id, kind, note))

    def pin(self, entity_id: str, *, on: bool = True) -> None:
        self.pin_calls.append((entity_id, on))

    def snooze(self, entity_id: str, until: datetime) -> None:
        self.snooze_calls.append((entity_id, until))

    def acknowledge_change(self, fingerprint: str) -> None:
        self.ack_calls.append(fingerprint)

    def review_queue(self) -> list[ReviewItem]:
        self.review_queue_calls += 1
        return self._review_items

    def people_at(self, entity_id: str) -> list[RankedContact]:
        self.people_at_calls.append(entity_id)
        return self._people

    def apply_graph_repair(self, repair_id: str) -> None:
        self.apply_repair_calls.append(repair_id)


def _make_repair_item(item_id: str = "REPAIR-001") -> ReviewItem:
    return ReviewItem(
        kind="repair",
        id=item_id,
        summary="Graph repair: missing_edge A → B",
        payload={"fingerprint": "fp-repair-001"},
    )


def _make_conflict_item(item_id: str = "CONFLICT-001") -> ReviewItem:
    return ReviewItem(
        kind="conflict",
        id=item_id,
        summary="Conflict on job.title for entity E-001",
        payload={"fingerprint": "fp-conflict-001"},
    )


def _make_person(entity_id: str = "e-alice", name: str = "Alice") -> RankedContact:
    return RankedContact(
        entity_id=entity_id,
        display_name=name,
        score=5.0,
        why=["overdue"],
        tier="A",
        last_interaction_at=_T0,
    )


# ---------------------------------------------------------------------------
# ReviewScreen tests
# ---------------------------------------------------------------------------


@pytest.mark.tui
@pytest.mark.anyio
async def test_review_screen_renders_items() -> None:
    """ReviewScreen renders review_queue() items in the DataTable."""
    items = [_make_repair_item(), _make_conflict_item()]
    spy = SpyFacade(review_items=items)

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        # Navigate to review screen via 'r'
        await pilot.press("r")
        await pilot.pause()

        # review_queue should have been called (at least once for mount)
        assert spy.review_queue_calls >= 1

        # DataTable must show 2 rows
        review_table = pilot.app.screen.query_one("#review-table")
        assert review_table.row_count == 2  # type: ignore[attr-defined]


@pytest.mark.tui
@pytest.mark.anyio
async def test_review_screen_empty_is_robust() -> None:
    """ReviewScreen is robust when review_queue() returns empty list."""
    spy = SpyFacade(review_items=[])

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()

        review_table = pilot.app.screen.query_one("#review-table")
        assert review_table.row_count == 0  # type: ignore[attr-defined]


@pytest.mark.tui
@pytest.mark.anyio
async def test_review_screen_a_calls_apply_graph_repair() -> None:
    """Pressing 'a' on a repair item calls facade.apply_graph_repair."""
    repair = _make_repair_item("REPAIR-42")
    spy = SpyFacade(review_items=[repair])

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        # Press 'a' on the repair row
        await pilot.press("a")
        await pilot.pause()

        assert len(spy.apply_repair_calls) == 1
        assert spy.apply_repair_calls[0] == "REPAIR-42"


@pytest.mark.tui
@pytest.mark.anyio
async def test_review_screen_a_no_op_on_conflict() -> None:
    """Pressing 'a' on a conflict item does NOT call apply_graph_repair."""
    conflict = _make_conflict_item("CONFLICT-99")
    spy = SpyFacade(review_items=[conflict])

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        assert spy.apply_repair_calls == []


@pytest.mark.tui
@pytest.mark.anyio
async def test_review_screen_escape_returns_to_queue() -> None:
    """Pressing 'escape' on the review screen returns to the queue."""
    spy = SpyFacade()

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        # Should be back on the queue screen
        queue_table = pilot.app.screen.query_one("#queue-table")
        assert queue_table is not None


# ---------------------------------------------------------------------------
# ContactPointsScreen tests
# ---------------------------------------------------------------------------


@pytest.mark.tui
@pytest.mark.anyio
async def test_contact_points_screen_renders_people() -> None:
    """ContactPointsScreen renders people returned by facade.people_at."""
    people = [_make_person("e-alice", "Alice"), _make_person("e-bob", "Bob")]
    spy = SpyFacade(people=people)

    # Open the ContactPointsScreen directly (as a standalone screen push)
    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        # Navigate: open detail for Alice, then press 'c' for contact points
        await pilot.press("enter")  # opens detail for Alice (first row)
        await pilot.pause()
        await pilot.press("c")  # push ContactPointsScreen
        await pilot.pause()

        # people_at should have been called with Alice's entity_id
        assert "e-alice" in spy.people_at_calls

        # DataTable shows 2 people
        cp_table = pilot.app.screen.query_one("#cp-table")
        assert cp_table.row_count == 2  # type: ignore[attr-defined]


@pytest.mark.tui
@pytest.mark.anyio
async def test_contact_points_screen_empty_is_robust() -> None:
    """ContactPointsScreen handles empty people_at() gracefully."""
    spy = SpyFacade(people=[])

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        cp_table = pilot.app.screen.query_one("#cp-table")
        assert cp_table.row_count == 0  # type: ignore[attr-defined]


@pytest.mark.tui
@pytest.mark.anyio
async def test_contact_points_screen_escape_returns_to_detail() -> None:
    """Pressing 'escape' on the contact-points screen returns to detail."""
    spy = SpyFacade()

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")  # → detail
        await pilot.pause()
        await pilot.press("c")  # → contact points
        await pilot.pause()
        await pilot.press("escape")  # → back to detail
        await pilot.pause()

        # Should be on detail screen now
        detail_content = pilot.app.screen.query_one("#detail-content")
        assert detail_content is not None


# ---------------------------------------------------------------------------
# LogInteractionModal tests
# ---------------------------------------------------------------------------


@pytest.mark.tui
@pytest.mark.anyio
async def test_log_modal_submit_calls_log_interaction() -> None:
    """LogInteractionModal submit calls facade.log_interaction with entity_id."""
    spy = SpyFacade()

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # open modal from queue
        await pilot.pause()
        # Submit without changing defaults
        await pilot.click("#submit-btn")
        await pilot.pause()

        assert len(spy.log_calls) == 1
        entity_id, kind, note = spy.log_calls[0]
        assert entity_id == "e-alice"
        assert kind == "note"  # default kind
        assert note is None  # no note entered


@pytest.mark.tui
@pytest.mark.anyio
async def test_log_modal_cancel_does_not_call_log_interaction() -> None:
    """Pressing Cancel in the modal does NOT call facade.log_interaction."""
    spy = SpyFacade()

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        await pilot.click("#cancel-btn")
        await pilot.pause()

        assert spy.log_calls == []


@pytest.mark.tui
@pytest.mark.anyio
async def test_log_modal_escape_does_not_call_log_interaction() -> None:
    """Pressing 'escape' in the modal dismisses it without calling log_interaction."""
    spy = SpyFacade()

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert spy.log_calls == []


@pytest.mark.tui
@pytest.mark.anyio
async def test_log_modal_from_detail_calls_log_interaction() -> None:
    """Pressing 'l' from the detail screen opens modal; submit calls log_interaction."""
    spy = SpyFacade()

    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")  # → detail
        await pilot.pause()
        await pilot.press("l")  # → modal
        await pilot.pause()
        await pilot.click("#submit-btn")
        await pilot.pause()

        assert len(spy.log_calls) == 1
        entity_id, _kind, _note = spy.log_calls[0]
        assert entity_id == "e-alice"
