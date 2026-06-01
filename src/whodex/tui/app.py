"""Textual TUI for whodex.

Two screens:
  - QueueScreen (home): priority queue DataTable with key bindings.
  - DetailScreen: full contact detail view.

Only the Whodex facade is called (invariant F7): tui imports facade/domain only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static

from whodex.facade.dto import ContactDetail, RankedContact


@runtime_checkable
class FacadeLike(Protocol):
    """Duck-typed protocol for the Whodex facade — only the methods TUI needs."""

    def priority_queue(
        self, limit: int = 50, *, include_snoozed: bool = False
    ) -> list[RankedContact]: ...

    def contact_detail(self, entity_id: str) -> ContactDetail | None: ...

    def log_interaction(self, entity_id: str) -> None: ...

    def pin(self, entity_id: str, *, on: bool = True) -> None: ...

    def snooze(self, entity_id: str, until: datetime) -> None: ...

    def acknowledge_change(self, fingerprint: str) -> None: ...


# ---------------------------------------------------------------------------
# Detail screen
# ---------------------------------------------------------------------------


class DetailScreen(Screen[None]):
    """Contact detail screen — shows all fields, timeline, open changes."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("b", "app.pop_screen", "Back"),
        Binding("a", "ack_change", "Ack change"),
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
      l        : log interaction with selected contact
      s        : snooze selected contact for 7 days
      p        : pin selected contact
      q        : quit
    """

    BINDINGS = [
        Binding("l", "log_interaction", "Log"),
        Binding("s", "snooze_contact", "Snooze"),
        Binding("p", "pin_contact", "Pin"),
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
        eid = self._selected_entity_id()
        if eid is not None:
            self._facade.log_interaction(eid)
            self._refresh_queue()

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
    """

    def __init__(self, facade: FacadeLike) -> None:
        super().__init__()
        self._facade = facade

    def on_mount(self) -> None:
        self.push_screen(QueueScreen(self._facade))
