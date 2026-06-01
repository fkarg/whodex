"""JSONL ledger mirror — append-only backup path for the SQLite ledger.

Public API
----------
append_jsonl(directory, stream, models)
    Append one JSON line per model to ``<directory>/<stream>.jsonl``.
    Creates the directory and file if they do not yet exist.

read_events_from_jsonl(directory) -> EventStream
    Read every stream file present under *directory*, validate each line
    back into the correct domain model, and return a reconstructed
    :class:`~whodex.domain.state.EventStream`.

Stream names match the three :class:`~whodex.domain.state.EventStream` fields:
``"observations"``, ``"interactions"``, ``"user_actions"``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.state import EventStream

# Map stream name → domain model used for validation on read-back.
_STREAM_MODEL: dict[str, type[BaseModel]] = {
    "observations": Observation,
    "interactions": Interaction,
    "user_actions": UserAction,
}


def append_jsonl(directory: Path, stream: str, models: Sequence[BaseModel]) -> None:
    """Append one ``model.model_dump_json()`` line per entry to ``<directory>/<stream>.jsonl``.

    The directory (and file) are created if they do not yet exist.
    Existing content is preserved — each call appends to the end.
    """
    if not models:
        return
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stream}.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        for model in models:
            fh.write(model.model_dump_json())
            fh.write("\n")


def read_events_from_jsonl(directory: Path) -> EventStream:
    """Reconstruct an :class:`~whodex.domain.state.EventStream` from JSONL files in *directory*.

    Each ``<stream>.jsonl`` file is read line-by-line; blank lines are skipped.
    Lines are validated with ``model_validate_json`` into the matching domain
    model.  Missing stream files are silently ignored (the list stays empty).
    """
    observations: list[Observation] = []
    interactions: list[Interaction] = []
    user_actions: list[UserAction] = []

    containers: dict[str, list] = {  # type: ignore[type-arg]
        "observations": observations,
        "interactions": interactions,
        "user_actions": user_actions,
    }

    for stream, model_cls in _STREAM_MODEL.items():
        path = directory / f"{stream}.jsonl"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                containers[stream].append(model_cls.model_validate_json(line))

    return EventStream(
        observations=observations,
        interactions=interactions,
        user_actions=user_actions,
    )
