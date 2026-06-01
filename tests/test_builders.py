from tests.conftest import _t, action, interaction, obs, raw
from whodex.domain.enums import UserActionType


def test_obs_builder_sets_hash_and_entity():
    o = obs(entity="E1", field="job.title", value="Eng")
    assert o.entity_id == "E1"
    assert o.value_hash


def test_builders_produce_unique_ids():
    a = obs(entity="E1", field="email", value="a@b.com")
    b = obs(entity="E1", field="email", value="c@d.com")
    assert a.id != b.id


def test_interaction_and_action_and_raw():
    assert interaction(entities=("E1",)).participant_ids == ("E1",)
    act = action(action_type=UserActionType.pin, target_type="field", target_id="E1:job.title")
    assert act.action_type == UserActionType.pin
    assert raw(identity={"email": "a@b.com"}, observed=_t(3)).source == "fake"
