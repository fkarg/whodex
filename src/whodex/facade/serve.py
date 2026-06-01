"""serve_tick — one testable unit of the serve loop.

One tick = sync + dispatch_notifications.  The infinite-loop wrapper in
``cli/main.py`` is deliberately thin and untested; this module contains the
pure, deterministic unit that tests exercise.

Deferred: FastAPI mount, watchdog/inotify integration.
"""

from __future__ import annotations

from dataclasses import dataclass

from whodex.facade.whodex import Whodex


@dataclass
class ServeTickReport:
    """Summary of a single serve tick."""

    notifications_dispatched: int
    entity_count: int


def serve_tick(facade: Whodex) -> ServeTickReport:
    """Run one sync + dispatch cycle and return a summary report.

    This function is pure of any loop; callers are responsible for
    scheduling repeated calls (e.g. via ``time.sleep``).
    """
    facade.sync()
    dispatched = facade.dispatch_notifications()
    entity_count = len(facade._app.projection.load())
    return ServeTickReport(
        notifications_dispatched=dispatched,
        entity_count=entity_count,
    )
