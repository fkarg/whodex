from __future__ import annotations

from collections.abc import Sequence

from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.state import EntityGraphState, EventStream


class InMemoryLedgerStore:
    def __init__(self) -> None:
        self._obs: list[Observation] = []
        self._int: list[Interaction] = []
        self._act: list[UserAction] = []

    def append_observations(self, observations: Sequence[Observation]) -> None:
        self._obs.extend(observations)

    def append_interactions(self, interactions: Sequence[Interaction]) -> None:
        self._int.extend(interactions)

    def append_user_actions(self, actions: Sequence[UserAction]) -> None:
        self._act.extend(actions)

    def read_events(self) -> EventStream:
        return EventStream(
            observations=list(self._obs),
            interactions=list(self._int),
            user_actions=list(self._act),
        )


class InMemoryProjectionStore:
    def __init__(self) -> None:
        self._states: EntityGraphState = {}

    def save(self, states: EntityGraphState) -> None:
        self._states = dict(states)

    def load(self) -> EntityGraphState:
        return dict(self._states)
