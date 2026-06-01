from hypothesis import given
from hypothesis import strategies as st

from tests.conftest import _t, action, obs
from whodex.domain.enums import EntityKind, Significance, UserActionType
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


# ---------------------------------------------------------------------------
# Item 1: pin suppresses Change
# ---------------------------------------------------------------------------


def test_pin_suppresses_change():
    """A pin flip does not emit a Change even though the displayed value differs from prev."""
    # First projection: source gives job.title="Eng"
    first = _project(
        EventStream(observations=[obs(entity="E1", field="job.title", value="Eng", observed=_t(1))])
    )
    assert first.states["E1"].fields["job.title"].value == "Eng"

    # Second projection: same source observation PLUS a pin that overrides with "Boss".
    # The displayed value changes from "Eng" to "Boss" but it is a pin flip, not a source
    # change, so no Change should be emitted.
    source_obs = obs(entity="E1", field="job.title", value="Eng", observed=_t(1))
    pin_action = action(
        action_type=UserActionType.pin,
        target_type="field",
        target_id="E1:job.title",
        entity="E1",
        payload={"field": "job.title", "value": "Boss"},
    )
    stream2 = EventStream(observations=[source_obs], user_actions=[pin_action])
    result = project(stream2, first.states, trust=DEFAULT_TRUST, kinds=KINDS, now=_t(10))

    fv = result.states["E1"].fields["job.title"]
    assert fv.value == "Boss"
    assert fv.pinned is True
    assert result.changes == []


# ---------------------------------------------------------------------------
# Item 2: unpin restores the source winner
# ---------------------------------------------------------------------------


def test_unpin_restores_source_winner():
    """An unpin after a pin removes the override; the source value wins and pinned is False."""
    source_obs = obs(entity="E1", field="job.title", value="Eng", observed=_t(1))
    pin_action = action(
        action_type=UserActionType.pin,
        target_type="field",
        target_id="E1:job.title",
        entity="E1",
        payload={"field": "job.title", "value": "Boss"},
        created=_t(2),
    )
    unpin_action = action(
        action_type=UserActionType.unpin,
        target_type="field",
        target_id="E1:job.title",
        entity="E1",
        payload={"field": "job.title"},
        created=_t(3),  # later than the pin
    )
    stream = EventStream(
        observations=[source_obs],
        user_actions=[pin_action, unpin_action],
    )
    result = _project(stream)

    fv = result.states["E1"].fields["job.title"]
    assert fv.value == "Eng"
    assert fv.pinned is False


# ---------------------------------------------------------------------------
# Item 3: multi-source conflict caps at one ConflictSuggestion per field
# ---------------------------------------------------------------------------


def test_three_source_conflict_caps_at_one_suggestion():
    """Three observations with different values → exactly one ConflictSuggestion (break in loop)."""
    # obsidian (trust 80) wins; google_contacts (60) and linkedin_ext (50) lose.
    winner_obs = obs(
        entity="E1", field="email", value="hi@example.com", source="obsidian", observed=_t(1)
    )
    loser1 = obs(
        entity="E1",
        field="email",
        value="other@example.com",
        source="google_contacts",
        observed=_t(1),
    )
    loser2 = obs(
        entity="E1",
        field="email",
        value="third@example.com",
        source="linkedin_ext",
        observed=_t(1),
    )
    stream = EventStream(observations=[winner_obs, loser1, loser2])
    result = _project(stream)

    assert result.states["E1"].fields["email"].value == "hi@example.com"
    assert len(result.conflict_suggestions) == 1
    assert result.conflict_suggestions[0].field == "email"


# ---------------------------------------------------------------------------
# Item 4: Change and ConflictSuggestion wiring assertions
# ---------------------------------------------------------------------------


def test_change_wiring_caused_by_and_significance():
    """On a value flip the Change points at the winning observation and has correct significance."""
    first_obs = obs(entity="E1", field="job.title", value="Eng", observed=_t(1))
    first = project(
        EventStream(observations=[first_obs]),
        None,
        trust=DEFAULT_TRUST,
        kinds=KINDS,
        now=_t(10),
    )

    second_obs = obs(entity="E1", field="job.title", value="Staff Eng", observed=_t(5))
    result = project(
        EventStream(observations=[second_obs]),
        first.states,
        trust=DEFAULT_TRUST,
        kinds=KINDS,
        now=_t(10),
    )

    assert len(result.changes) == 1
    ch = result.changes[0]
    # caused_by_observation must be the winning observation's id
    assert ch.caused_by_observation == second_obs.id
    # job.title is volatile → Significance.notable
    assert ch.significance == Significance.notable


def test_conflict_suggestion_wiring_winner_and_loser_ids():
    """ConflictSuggestion.winning_observation_id and disagreeing_observation_id are correct."""
    # obsidian (trust 80) > linkedin_ext (trust 50)
    winner_obs = obs(
        entity="E1", field="job.title", value="Truth", source="obsidian", observed=_t(1)
    )
    loser_obs = obs(
        entity="E1", field="job.title", value="Stale", source="linkedin_ext", observed=_t(9)
    )
    stream = EventStream(observations=[winner_obs, loser_obs])
    result = _project(stream)

    assert len(result.conflict_suggestions) == 1
    cs = result.conflict_suggestions[0]
    assert cs.winning_observation_id == winner_obs.id
    assert cs.disagreeing_observation_id == loser_obs.id


# ---------------------------------------------------------------------------
# Item 5: same-trust supersession must NOT produce a conflict (DESIGN §6.5)
# ---------------------------------------------------------------------------


def test_same_trust_supersession_emits_no_conflict():
    """Two observations from the same source (equal trust) at different times with different
    values represent normal value supersession (history), not a §6.5 conflict.

    The newer value wins, and conflict_suggestions must be empty.
    The existing lower-trust case (obsidian vs linkedin_ext) must still emit a conflict.
    """
    # Both observations use source="fake" (trust 10 == trust 10).
    # t5 beats t1 under the tiebreak (observed_at), so "Staff Engineer" wins.
    stream = EventStream(
        observations=[
            obs(entity="E1", field="job.title", value="Engineer", source="fake", observed=_t(1)),
            obs(
                entity="E1",
                field="job.title",
                value="Staff Engineer",
                source="fake",
                observed=_t(5),
            ),
        ]
    )
    result = _project(stream)

    # Newest value should win.
    assert result.states["E1"].fields["job.title"].value == "Staff Engineer"
    # No conflict — both observations carry equal trust, so this is supersession, not §6.5.
    assert result.conflict_suggestions == []

    # Sanity-check: lower-trust case still DOES emit a conflict.
    stream2 = EventStream(
        observations=[
            obs(entity="E1", field="job.title", value="Truth", source="obsidian", observed=_t(1)),
            obs(
                entity="E1",
                field="job.title",
                value="Stale",
                source="linkedin_ext",
                observed=_t(9),
            ),
        ]
    )
    result2 = _project(stream2)
    assert len(result2.conflict_suggestions) == 1
    assert result2.conflict_suggestions[0].reason == "lower_trust_disagrees"
