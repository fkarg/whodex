"""TUI tests: thin behavioural layer only — no business logic.

Uses a spy facade (FacadeLike implementation) to verify that the TUI:
  (a) mounts and renders without crashing,
  (b) calls facade methods on the correct key-presses.

Snapshot test is skipped (snap_compare requires --snapshot-update on first run;
we rely on Pilot assertions instead for CI stability).
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
    """Minimal FacadeLike implementation for testing."""

    def __init__(self) -> None:
        self.pin_calls: list[tuple[str, bool]] = []
        self.log_calls: list[tuple[str, str, str | None]] = []
        self.detail_calls: list[str] = []
        self.snooze_calls: list[tuple[str, datetime]] = []
        self.ack_calls: list[str] = []
        self.review_queue_calls: int = 0
        self.people_at_calls: list[str] = []
        self.apply_repair_calls: list[str] = []

        self._queue = [
            RankedContact(
                entity_id="e-alice",
                display_name="Alice",
                score=10.0,
                why=["overdue"],
                tier="A",
                last_interaction_at=_T0,
            ),
            RankedContact(
                entity_id="e-bob",
                display_name="Bob",
                score=5.0,
                why=["reminder"],
                tier="B",
                last_interaction_at=None,
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
            display_name="Alice" if entity_id == "e-alice" else "Bob",
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
        return []

    def people_at(self, entity_id: str) -> list[RankedContact]:
        self.people_at_calls.append(entity_id)
        return []

    def apply_graph_repair(self, repair_id: str) -> None:
        self.apply_repair_calls.append(repair_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _queue_table(pilot: object) -> object:  # type: ignore[return]
    """Return the queue DataTable from the current screen."""
    # The QueueScreen is pushed as the first screen; query from there.
    app = pilot.app  # type: ignore[union-attr]
    screen = app.screen
    return screen.query_one("#queue-table")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.tui
@pytest.mark.anyio
async def test_tui_queue_shows_two_rows() -> None:
    """Queue DataTable has exactly 2 rows (one per canned contact)."""
    spy = SpyFacade()
    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        table = _queue_table(pilot)
        assert table.row_count == 2  # type: ignore[attr-defined]


@pytest.mark.tui
@pytest.mark.anyio
async def test_tui_press_p_calls_pin() -> None:
    """Pressing 'p' calls facade.pin with the selected entity_id."""
    spy = SpyFacade()
    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert len(spy.pin_calls) == 1
        assert spy.pin_calls[0][0] == "e-alice"  # first row selected by default


@pytest.mark.tui
@pytest.mark.anyio
async def test_tui_press_l_opens_modal_and_submit_calls_log_interaction() -> None:
    """Pressing 'l' opens the LogInteractionModal; submitting calls facade.log_interaction."""
    spy = SpyFacade()
    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        # Modal should be open — click the submit button
        await pilot.click("#submit-btn")
        await pilot.pause()
        assert len(spy.log_calls) == 1
        assert spy.log_calls[0][0] == "e-alice"  # entity_id is first element of tuple


@pytest.mark.tui
@pytest.mark.anyio
async def test_tui_press_enter_pushes_detail_screen() -> None:
    """Pressing 'enter' (DataTable RowSelected) opens the Contact Detail screen."""
    spy = SpyFacade()
    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # facade.contact_detail must have been called for the first row
        assert len(spy.detail_calls) == 1
        assert spy.detail_calls[0] == "e-alice"


@pytest.mark.tui
@pytest.mark.anyio
async def test_tui_detail_escape_returns_to_queue() -> None:
    """After opening the detail screen, pressing 'escape' returns to the queue."""
    spy = SpyFacade()
    async with WhodexTUI(spy).run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # Now on detail screen — press escape to go back
        await pilot.press("escape")
        await pilot.pause()
        # Should be back to queue — table is visible with 2 rows
        table = _queue_table(pilot)
        assert table.row_count == 2  # type: ignore[attr-defined]
