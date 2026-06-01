from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from whodex.domain.state import Notification


@dataclass
class DeliveryResult:
    delivered: bool
    detail: str = field(default="")


class Notifier(Protocol):
    name: str

    def supports(self, n: Notification) -> bool: ...

    def send(self, n: Notification) -> DeliveryResult: ...
