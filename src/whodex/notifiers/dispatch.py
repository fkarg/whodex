from __future__ import annotations

from whodex.notifiers.interface import Notifier
from whodex.store.interfaces import NotificationStore


class NotificationDispatcher:
    """Fans pending notifications out to every registered Notifier that supports them.

    Idempotent: calling dispatch() multiple times delivers each (notification, sink)
    pair at most once — already-delivered sinks are skipped.
    """

    def __init__(self, notifiers: list[Notifier], store: NotificationStore) -> None:
        self._notifiers = notifiers
        self._store = store

    def dispatch(self) -> int:
        """Dispatch all pending notifications.  Returns count of (notification, sink) deliveries."""
        count = 0
        for n in self._store.pending():
            for notifier in self._notifiers:
                if not notifier.supports(n):
                    continue
                if notifier.name in n.delivered_to:
                    continue
                result = notifier.send(n)
                if result.delivered:
                    self._store.mark_delivered(n.id, notifier.name)
                    count += 1
        return count
