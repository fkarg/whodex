from __future__ import annotations

from typing import Protocol

from ulid import ULID


class IdFactory(Protocol):
    def new(self) -> str: ...


class UlidIdFactory:
    def new(self) -> str:
        return str(ULID())


class SequentialIdFactory:
    """Deterministic IDs for tests — stable snapshots."""

    def __init__(self, prefix: str = "ID") -> None:
        self._prefix = prefix
        self._n = 0

    def new(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n:08d}"
