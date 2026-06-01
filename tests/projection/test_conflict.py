from tests.conftest import _t, obs
from whodex.domain.trust import DEFAULT_TRUST
from whodex.projection.conflict import resolve_field


def test_higher_trust_wins_regardless_of_recency():
    older_high = obs(entity="E1", field="job.title", value="A", source="obsidian", observed=_t(1))
    newer_low = obs(
        entity="E1", field="job.title", value="B", source="linkedin_ext", observed=_t(9)
    )
    fv, _winner, losers = resolve_field([older_high, newer_low], pinned=None, trust=DEFAULT_TRUST)
    assert fv.value == "A"
    assert losers[0].value == "B"


def test_within_equal_trust_newest_observed_wins():
    old = obs(entity="E1", field="job.title", value="A", source="fake", observed=_t(1))
    new = obs(entity="E1", field="job.title", value="B", source="fake", observed=_t(5))
    fv, _w, _l = resolve_field([old, new], pinned=None, trust=DEFAULT_TRUST)
    assert fv.value == "B"


def test_pin_beats_everything():
    high = obs(entity="E1", field="job.title", value="A", source="obsidian", observed=_t(9))
    fv, winner, _l = resolve_field([high], pinned="PINNED", trust=DEFAULT_TRUST)
    assert fv.value == "PINNED"
    assert fv.pinned is True
    assert winner is None  # pin is not an observation


def test_deterministic_tiebreak_is_order_independent():
    a = obs(entity="E1", field="job.title", value="A", source="fake", observed=_t(1))
    b = obs(entity="E1", field="job.title", value="B", source="fake", observed=_t(1))
    fv1, _, _ = resolve_field([a, b], pinned=None, trust=DEFAULT_TRUST)
    fv2, _, _ = resolve_field([b, a], pinned=None, trust=DEFAULT_TRUST)
    assert fv1.value == fv2.value  # order-independent
