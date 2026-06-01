from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from whodex.domain.events import Interaction, Observation, UserAction
from whodex.domain.state import EventStream
from whodex.store import mappers
from whodex.store.rows import InteractionRow, ObservationRow, UserActionRow


class SqliteLedgerStore:
    def __init__(self, url: str = "sqlite://") -> None:
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self._engine)

    def append_observations(self, observations: Sequence[Observation]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.obs_to_row(o) for o in observations])
            s.commit()

    def append_interactions(self, interactions: Sequence[Interaction]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.interaction_to_row(i) for i in interactions])
            s.commit()

    def append_user_actions(self, actions: Sequence[UserAction]) -> None:
        with Session(self._engine) as s:
            s.add_all([mappers.action_to_row(a) for a in actions])
            s.commit()

    def read_events(self) -> EventStream:
        with Session(self._engine) as s:
            obs = [mappers.row_to_obs(r) for r in s.exec(select(ObservationRow)).all()]
            ints = [mappers.row_to_interaction(r) for r in s.exec(select(InteractionRow)).all()]
            acts = [mappers.row_to_action(r) for r in s.exec(select(UserActionRow)).all()]
        return EventStream(observations=obs, interactions=ints, user_actions=acts)
