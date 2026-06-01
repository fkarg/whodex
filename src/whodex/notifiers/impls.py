from __future__ import annotations

from whodex.domain.state import Notification
from whodex.notifiers.interface import DeliveryResult


class TUINotifier:
    """Records delivered notifications in-memory; real TUI surfacing comes in P1g-5."""

    name: str = "tui"

    def __init__(self) -> None:
        self.delivered: list[Notification] = []

    def supports(self, n: Notification) -> bool:
        return True

    def send(self, n: Notification) -> DeliveryResult:
        self.delivered.append(n)
        return DeliveryResult(delivered=True)


# Alias: ConsoleNotifier is the same thing under an alternate name.
ConsoleNotifier = TUINotifier
