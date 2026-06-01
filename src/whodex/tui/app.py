"""Textual TUI for whodex.

Screens:
  - QueueScreen (home): priority queue DataTable with key bindings.
  - DetailScreen: full contact detail view.
  - ReviewScreen: review queue (conflicts + graph repairs).
  - ContactPointsScreen: people at an org/location entity.
  - LogInteractionModal: modal to log an interaction with kind + note.

Only the Whodex facade is called (invariant F7): tui imports facade/domain only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Static

from whodex.facade.dto import ContactDetail, RankedContact, ReviewItem


@runtime_checkable
class FacadeLike(Protocol):
    """Duck-typed protocol for the Whodex facade — only the methods TUI needs."""

    def priority_queue(
        self, limit: int = 50, *, include_snoozed: bool = False
    ) -> list[RankedContact]: ...

    def contact_detail(self, entity_id: str) -> ContactDetail | None: ...

    def log_interaction(
        self,
        entity_id: str,
        kind: str = "note",
        *,
        note: str | None = None,
    ) -> None: ...

    def pin(self, entity_id: str, *, on: bool = True) -> None: ...

    def snooze(self, entity_id: str, until: datetime) -> None: ...

    def acknowledge_change(self, fingerprint: str) -> None: ...

    def review_queue(self) -> list[ReviewItem]: ...

    def people_at(self, entity_id: str) -> list[RankedContact]: ...

    def apply_graph_repair(self, repair_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Log Interaction Modal
# ---------------------------------------------------------------------------

_INTERACTION_KINDS = [
    ("Note", "note"),
    ("Call", "call"),
    ("Email", "email"),
    ("Meeting (met)", "met"),
    ("Message", "message"),
    ("Introduced", "introduced"),
]


class LogInteractionModal(ModalScreen[None]):
    """Modal screen to log an interaction with kind + optional note."""

    DEFAULT_CSS = """
    LogInteractionModal {
        align: center middle;
    }
    #modal-box {
        width: 60;
        height: auto;
        border: thick $primary;
        padding: 1 2;
        background: $surface;
    }
    #modal-title {
        text-align: center;
        margin-bottom: 1;
        color: $text;
    }
    #kind-select {
        margin-bottom: 1;
    }
    #note-input {
        margin-bottom: 1;
    }
    #modal-buttons {
        align: center middle;
        height: auto;
    }
    Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Cancel"),
    ]

    def __init__(self, facade: FacadeLike, entity_id: str) -> None:
        super().__init__()
        self._facade = facade
        self._entity_id = entity_id

    def compose(self) -> ComposeResult:
        with Static(id="modal-box"):
            yield Label("Log Interaction", id="modal-title")
            yield Select(
                options=_INTERACTION_KINDS,
                value="note",
                id="kind-select",
            )
            yield Input(placeholder="Optional note...", id="note-input")
            with Static(id="modal-buttons"):
                yield Button("Submit", variant="primary", id="submit-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "submit-btn":
            self._submit()

    def _submit(self) -> None:
        kind_select = self.query_one("#kind-select", Select)
        note_input = self.query_one("#note-input", Input)
        kind = str(kind_select.value) if kind_select.value else "note"
        note = note_input.value.strip() or None
        self._facade.log_interaction(self._entity_id, kind, note=note)
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Review / Maintenance screen
# ---------------------------------------------------------------------------

_REVIEW_COL_LABELS = ("Kind", "Summary", "ID")


class ReviewScreen(Screen[None]):
    """Review queue screen — conflicts, repairs, merge suggestions.

    Key bindings:
      a      : apply graph repair for the selected item (repair kind only)
      d      : dismiss the selected item (conflict kind)
      escape : back to queue
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("b", "app.pop_screen", "Back"),
        Binding("a", "apply_repair", "Apply repair"),
        Binding("d", "dismiss_item", "Dismiss"),
    ]

    def __init__(self, facade: FacadeLike) -> None:
        super().__init__()
        self._facade = facade
        self._items: list[ReviewItem] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(id="review-count")
        yield DataTable(id="review-table", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#review-table", DataTable)
        for label in _REVIEW_COL_LABELS:
            table.add_column(label)
        self._refresh()

    def _refresh(self) -> None:
        self._items = self._facade.review_queue()
        table = self.query_one("#review-table", DataTable)
        table.clear()
        for item in self._items:
            summary = item.summary[:60] + "…" if len(item.summary) > 60 else item.summary
            table.add_row(item.kind, summary, item.id, key=item.id)
        count_label = self.query_one("#review-count", Label)
        count_label.update(f"{len(self._items)} item(s) in review queue")

    def _selected_item(self) -> ReviewItem | None:
        table = self.query_one("#review-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            ordered = list(table.ordered_rows)
            if not ordered:
                return None
            row = ordered[table.cursor_row]
            item_id = str(row.key.value) if row.key.value is not None else None
            if item_id is None:
                return None
            return next((i for i in self._items if i.id == item_id), None)
        except (IndexError, AttributeError):
            return None

    def action_apply_repair(self) -> None:
        item = self._selected_item()
        if item is not None and item.kind == "repair":
            self._facade.apply_graph_repair(item.id)
            self._refresh()

    def action_dismiss_item(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        # For conflicts: facade has acknowledge_change (by fingerprint)
        # or dismiss_reminder — use whatever is available.
        # The facade may expose dismiss_reminder; we try fingerprint-based dismiss.
        fp = item.payload.get("fingerprint", "")
        if fp and hasattr(self._facade, "acknowledge_change"):
            self._facade.acknowledge_change(str(fp))
            self._refresh()


# ---------------------------------------------------------------------------
# Contact Points screen
# ---------------------------------------------------------------------------

_CP_COL_LABELS = ("Name", "Tier", "Why now", "Score")


class ContactPointsScreen(Screen[None]):
    """Shows people at an org / location entity (via facade.people_at).

    Reachable from DetailScreen via 'c'.
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("b", "app.pop_screen", "Back"),
    ]

    def __init__(self, facade: FacadeLike, entity_id: str) -> None:
        super().__init__()
        self._facade = facade
        self._entity_id = entity_id
        self._people: list[RankedContact] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(id="cp-count")
        yield DataTable(id="cp-table", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#cp-table", DataTable)
        for label in _CP_COL_LABELS:
            table.add_column(label)
        self._refresh()

    def _refresh(self) -> None:
        self._people = self._facade.people_at(self._entity_id)
        table = self.query_one("#cp-table", DataTable)
        table.clear()
        for rc in self._people:
            why_str = "; ".join(rc.why) if rc.why else ""
            score_str = f"{rc.score:.2f}" if rc.score != float("-inf") else "snoozed"
            table.add_row(
                rc.display_name or rc.entity_id,
                rc.tier,
                why_str,
                score_str,
                key=rc.entity_id,
            )
        count_label = self.query_one("#cp-count", Label)
        count_label.update(f"{len(self._people)} contact(s) at this entity")


# ---------------------------------------------------------------------------
# Detail screen
# ---------------------------------------------------------------------------


class DetailScreen(Screen[None]):
    """Contact detail screen — shows all fields, timeline, open changes."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("b", "app.pop_screen", "Back"),
        Binding("a", "ack_change", "Ack change"),
        Binding("c", "contact_points", "Contact points"),
        Binding("l", "log_interaction", "Log"),
    ]

    def __init__(self, facade: FacadeLike, entity_id: str) -> None:
        super().__init__()
        self._facade = facade
        self._entity_id = entity_id
        self._detail: ContactDetail | None = None

    def on_mount(self) -> None:
        self._detail = self._facade.contact_detail(self._entity_id)
        self._render_detail()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="detail-content")
        yield Footer()

    def _render_detail(self) -> None:
        content = self.query_one("#detail-content", Static)
        d = self._detail
        if d is None:
            content.update(f"[red]Contact {self._entity_id!r} not found.[/red]")
            return

        lines: list[str] = []
        lines.append(f"[bold]{d.display_name or d.entity_id}[/bold]  kind={d.kind}")
        lines.append("")

        if d.fields:
            lines.append("[underline]Fields[/underline]")
            for name, fe in sorted(d.fields.items()):
                lines.append(f"  {name}: {fe.value!r}  [{fe.staleness}]")
            lines.append("")

        if d.contact_points:
            lines.append("[underline]Contact points[/underline]")
            for cp in d.contact_points:
                lines.append(f"  {cp}")
            lines.append("")

        if d.timeline:
            lines.append("[underline]Timeline[/underline]")
            for t in d.timeline[:10]:
                ts = t.occurred_at.strftime("%Y-%m-%d")
                lines.append(f"  {ts}  {t.kind}  {t.summary or ''}")
            lines.append("")

        if d.open_changes:
            lines.append("[underline]Open changes[/underline]")
            for ch in d.open_changes:
                lines.append(
                    f"  {ch.get('field')}: {ch.get('old_value')!r} → {ch.get('new_value')!r}"
                )
            lines.append("")

        content.update("\n".join(lines))

    def action_ack_change(self) -> None:
        d = self._detail
        if d and d.open_changes:
            fp = d.open_changes[0].get("fingerprint", "")
            if fp:
                self._facade.acknowledge_change(str(fp))

    def action_contact_points(self) -> None:
        """Push the ContactPointsScreen for the current entity."""
        self.app.push_screen(ContactPointsScreen(self._facade, self._entity_id))

    def action_log_interaction(self) -> None:
        """Open the LogInteractionModal for the current entity."""

        def _on_dismiss(result: None) -> None:
            # After modal closes, reload detail
            self._detail = self._facade.contact_detail(self._entity_id)
            self._render_detail()

        self.app.push_screen(LogInteractionModal(self._facade, self._entity_id), _on_dismiss)


# ---------------------------------------------------------------------------
# Queue screen (home)
# ---------------------------------------------------------------------------


_COL_LABELS = ("Name", "Tier", "Why now", "Score")


class QueueScreen(Screen[None]):
    """Priority queue home screen.

    Key bindings:
      j / down : cursor down in the DataTable
      k / up   : cursor up in the DataTable
      enter    : open detail for selected contact (via DataTable.RowSelected)
      l        : open log-interaction modal for selected contact
      s        : snooze selected contact for 7 days
      p        : pin selected contact
      r        : open review/maintenance screen
      q        : quit
    """

    BINDINGS = [
        Binding("l", "log_interaction", "Log"),
        Binding("s", "snooze_contact", "Snooze"),
        Binding("p", "pin_contact", "Pin"),
        Binding("r", "open_review", "Review"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, facade: FacadeLike) -> None:
        super().__init__()
        self._facade = facade
        self._contacts: list[RankedContact] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(id="queue-count")
        yield DataTable(id="queue-table", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        for label in _COL_LABELS:
            table.add_column(label)
        self._refresh_queue()

    def _refresh_queue(self) -> None:
        self._contacts = self._facade.priority_queue()
        table = self.query_one("#queue-table", DataTable)
        table.clear()

        for rc in self._contacts:
            why_str = "; ".join(rc.why) if rc.why else ""
            score_str = f"{rc.score:.2f}" if rc.score != float("-inf") else "snoozed"
            table.add_row(
                rc.display_name or rc.entity_id,
                rc.tier,
                why_str,
                score_str,
                key=rc.entity_id,
            )

        count_label = self.query_one("#queue-count", Label)
        count_label.update(f"{len(self._contacts)} contact(s) in queue")

    def _selected_entity_id(self) -> str | None:
        """Return the entity_id of the currently cursor-highlighted row, or None."""
        table = self.query_one("#queue-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            ordered = list(table.ordered_rows)
            if not ordered:
                return None
            row = ordered[table.cursor_row]
            # RowKey.value is the key we passed to add_row(key=...)
            return str(row.key.value) if row.key.value is not None else None
        except (IndexError, AttributeError):
            return None

    # ------------------------------------------------------------------
    # DataTable event: row selected via Enter key
    # ------------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the detail screen when a row is selected (Enter key)."""
        eid = str(event.row_key.value) if event.row_key.value is not None else None
        if eid is not None:
            self.app.push_screen(DetailScreen(self._facade, eid))

    # ------------------------------------------------------------------
    # Actions bound to keys
    # ------------------------------------------------------------------

    def action_log_interaction(self) -> None:
        """Open the LogInteractionModal for the selected entity."""
        eid = self._selected_entity_id()
        if eid is not None:

            def _on_dismiss(result: None) -> None:
                self._refresh_queue()

            self.app.push_screen(LogInteractionModal(self._facade, eid), _on_dismiss)

    def action_snooze_contact(self) -> None:
        eid = self._selected_entity_id()
        if eid is not None:
            until = datetime.now(UTC) + timedelta(days=7)
            self._facade.snooze(eid, until)
            self._refresh_queue()

    def action_pin_contact(self) -> None:
        eid = self._selected_entity_id()
        if eid is not None:
            self._facade.pin(eid, on=True)
            self._refresh_queue()

    def action_open_review(self) -> None:
        """Push the review/maintenance screen."""
        self.app.push_screen(ReviewScreen(self._facade))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class WhodexTUI(App[None]):
    """Textual TUI application for whodex."""

    CSS = """
    #queue-count {
        padding: 0 1;
        color: $text-muted;
    }
    #detail-content {
        padding: 1 2;
    }
    #review-count {
        padding: 0 1;
        color: $text-muted;
    }
    #cp-count {
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, facade: FacadeLike) -> None:
        super().__init__()
        self._facade = facade

    def on_mount(self) -> None:
        self.push_screen(QueueScreen(self._facade))
