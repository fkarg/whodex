from datetime import UTC, datetime

from tests.conftest import action, interaction
from whodex.domain.enums import EntityKind, InteractionKind, UserActionType
from whodex.domain.state import EntityState, EventStream, FieldValue
from whodex.engine.scoring import ScoringConfig, build_score_inputs

NOW = datetime(2026, 3, 1, tzinfo=UTC)
CFG = ScoringConfig()


def _person_state(eid="E1", name="Jane", fields=None):
    return EntityState(
        entity_id=eid, kind=EntityKind.person, display_name=name, fields=fields or {}
    )


def _fv(field, value):
    return FieldValue(
        field=field, value=value, source_kind="obsidian", observed_at=NOW, ingested_at=NOW
    )


def test_builds_one_input_per_person_with_last_interaction():
    states = {"E1": _person_state()}
    events = EventStream(
        interactions=[
            interaction(
                entities=("E1",),
                kind=InteractionKind.met,
                occurred=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            interaction(
                entities=("E1",),
                kind=InteractionKind.call,
                occurred=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        ]
    )
    inputs = build_score_inputs(states, events, cfg=CFG, now=NOW)
    assert len(inputs) == 1
    assert inputs[0].last_interaction_at == datetime(2026, 2, 1, tzinfo=UTC)


def test_cadence_and_tier_from_fields_else_defaults():
    states = {
        "E1": _person_state(
            fields={
                "person.cadence_days": _fv("person.cadence_days", 45),
                "person.importance": _fv("person.importance", "inner"),
            }
        )
    }
    si = build_score_inputs(states, EventStream(), cfg=CFG, now=NOW)[0]
    assert si.cadence_days == 45
    assert si.tier == "inner"
    bare = build_score_inputs({"E2": _person_state(eid="E2")}, EventStream(), cfg=CFG, now=NOW)[0]
    assert bare.tier == "loose"
    assert bare.cadence_days == CFG.cadence_default["loose"]


def test_non_person_entities_are_skipped():
    org = EntityState(entity_id="O1", kind=EntityKind.organisation, display_name="Kolai")
    assert build_score_inputs({"O1": org}, EventStream(), cfg=CFG, now=NOW) == []


def test_pin_and_snooze_from_user_actions():
    states = {"E1": _person_state()}
    events = EventStream(
        user_actions=[
            action(
                action_type=UserActionType.pin, target_type="contact", target_id="E1", entity="E1"
            ),
            action(
                action_type=UserActionType.snooze,
                target_type="contact",
                target_id="E1",
                entity="E1",
                payload={"until": "2026-04-01T00:00:00+00:00"},
            ),
        ]
    )
    si = build_score_inputs(states, events, cfg=CFG, now=NOW)[0]
    assert si.pinned is True
    assert si.snoozed_until == datetime(2026, 4, 1, tzinfo=UTC)


def test_malformed_cadence_falls_back_to_tier_default():
    # "abc" is not a valid integer — should fall back to the tier default
    states_abc = {
        "E1": _person_state(fields={"person.cadence_days": _fv("person.cadence_days", "abc")})
    }
    si_abc = build_score_inputs(states_abc, EventStream(), cfg=CFG, now=NOW)[0]
    assert si_abc.cadence_days == CFG.cadence_default["loose"]

    # None value — should also fall back to the tier default
    states_none = {
        "E2": _person_state(
            eid="E2",
            fields={"person.cadence_days": _fv("person.cadence_days", None)},
        )
    }
    si_none = build_score_inputs(states_none, EventStream(), cfg=CFG, now=NOW)[0]
    assert si_none.cadence_days == CFG.cadence_default["loose"]


def test_malformed_snooze_payload_is_ignored():
    states = {"E1": _person_state()}
    events = EventStream(
        user_actions=[
            action(
                action_type=UserActionType.pin,
                target_type="contact",
                target_id="E1",
                entity="E1",
            ),
            action(
                action_type=UserActionType.snooze,
                target_type="contact",
                target_id="E1",
                entity="E1",
                payload={"until": "not-a-date"},
            ),
        ]
    )
    si = build_score_inputs(states, events, cfg=CFG, now=NOW)[0]
    assert si.snoozed_until is None
    assert si.pinned is True  # pin action must be unaffected


def test_unpin_clears_pin():
    states = {"E1": _person_state()}
    events = EventStream(
        user_actions=[
            action(
                action_type=UserActionType.pin,
                target_type="contact",
                target_id="E1",
                entity="E1",
                created=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            action(
                action_type=UserActionType.unpin,
                target_type="contact",
                target_id="E1",
                entity="E1",
                created=datetime(2026, 1, 2, tzinfo=UTC),
            ),
        ]
    )
    si = build_score_inputs(states, events, cfg=CFG, now=NOW)[0]
    assert si.pinned is False
