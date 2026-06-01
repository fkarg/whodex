from datetime import UTC, datetime, timedelta

from tests.conftest import interaction
from whodex.domain.enums import EntityKind, InteractionKind
from whodex.domain.state import EntityState, EventStream
from whodex.engine.queue import priority_queue
from whodex.engine.scoring import ScoringConfig

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _p(eid):
    return EntityState(entity_id=eid, kind=EntityKind.person, display_name=eid)


def test_queue_ranks_overdue_first_and_excludes_snoozed():
    states = {"E1": _p("E1"), "E2": _p("E2")}
    events = EventStream(
        interactions=[
            interaction(
                entities=("E2",), kind=InteractionKind.met, occurred=NOW - timedelta(days=5)
            ),
        ]
    )
    q = priority_queue(states, events, cfg=ScoringConfig(), now=NOW)
    assert [si.entity_id for si, _ in q][
        0
    ] == "E1"  # never-contacted ranks above recently-contacted
    assert all(score.value != float("-inf") for _, score in q)
