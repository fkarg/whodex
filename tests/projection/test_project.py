from hypothesis import given
from hypothesis import strategies as st

from tests.conftest import _t, action, obs
from whodex.domain.enums import EntityKind, UserActionType
from whodex.domain.state import EventStream
from whodex.domain.trust import DEFAULT_TRUST
from whodex.projection.project import project

KINDS = {"E1": EntityKind.person}


def _project(events, prev=None):
    return project(events, prev, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(10))


def test_initial_fill_is_not_a_change():
    stream = EventStream(observations=[obs(entity="E1", field="job.title", value="Eng")])
    result = _project(stream)
    assert result.states["E1"].fields["job.title"].value == "Eng"
    assert result.changes == []  # null -> value is an initial fill


def test_value_flip_emits_exactly_one_change():
    first = _project(
        EventStream(observations=[obs(entity="E1", field="job.title", value="Eng", observed=_t(1))])
    )
    stream2 = EventStream(
        observations=[obs(entity="E1", field="job.title", value="Staff Eng", observed=_t(5))]
    )
    result = project(stream2, first.states, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(10))
    assert len(result.changes) == 1
    assert result.changes[0].old_value == "Eng"
    assert result.changes[0].new_value == "Staff Eng"


def test_reproject_same_data_emits_no_change():
    stream = EventStream(observations=[obs(entity="E1", field="job.title", value="Eng")])
    first = _project(stream)
    second = project(stream, first.states, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(10))
    assert second.changes == []


def test_cosmetic_diff_is_not_a_change():
    first = _project(
        EventStream(
            observations=[obs(entity="E1", field="job.title", value="Staff Eng", observed=_t(1))]
        )
    )
    stream2 = EventStream(
        observations=[obs(entity="E1", field="job.title", value="  Staff   Eng ", observed=_t(5))]
    )
    result = project(stream2, first.states, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(10))
    assert result.changes == []


def test_lower_trust_disagreement_emits_conflict_not_change():
    stream = EventStream(
        observations=[
            obs(entity="E1", field="job.title", value="Truth", source="obsidian", observed=_t(1)),
            obs(
                entity="E1", field="job.title", value="Stale", source="linkedin_ext", observed=_t(9)
            ),
        ]
    )
    result = _project(stream)
    assert result.states["E1"].fields["job.title"].value == "Truth"
    assert result.changes == []
    assert len(result.conflict_suggestions) == 1
    assert result.conflict_suggestions[0].reason == "lower_trust_disagrees"


def test_pin_overlay_makes_pinned_value_win():
    stream = EventStream(
        observations=[obs(entity="E1", field="job.title", value="FromSource", source="obsidian")],
        user_actions=[
            action(
                action_type=UserActionType.pin,
                target_type="field",
                target_id="E1:job.title",
                entity="E1",
                payload={"field": "job.title", "value": "Pinned"},
            )
        ],
    )
    result = _project(stream)
    assert result.states["E1"].fields["job.title"].value == "Pinned"
    assert result.states["E1"].fields["job.title"].pinned is True


@given(values=st.lists(st.text(min_size=1, max_size=5), min_size=1, max_size=6))
def test_projection_is_order_independent(values):
    from tests.conftest import obs

    base = [
        obs(entity="E1", field="job.title", value=v, observed=_t(i + 1))
        for i, v in enumerate(values)
    ]
    forward = project(
        EventStream(observations=base), None, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(20)
    )
    backward = project(
        EventStream(observations=list(reversed(base))),
        None,
        trust=DEFAULT_TRUST,
        kinds=KINDS,
        now=_t(20),
    )
    assert (
        forward.states["E1"].fields["job.title"].value
        == backward.states["E1"].fields["job.title"].value
    )
