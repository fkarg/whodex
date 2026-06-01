from datetime import UTC, datetime, timedelta

from whodex.engine.scoring import ScoreInput, ScoringConfig, score_contact

NOW = datetime(2026, 3, 1, tzinfo=UTC)
CFG = ScoringConfig()


def _si(**kw):
    base = dict(
        entity_id="E1",
        display_name="Jane",
        last_interaction_at=None,
        cadence_days=30,
        tier="loose",
        pinned=False,
        snoozed_until=None,
        open_change_kinds=(),
    )
    base.update(kw)
    return ScoreInput(**base)


def test_snoozed_contact_is_excluded():
    s = score_contact(_si(snoozed_until=NOW + timedelta(days=5)), CFG, NOW)
    assert s.value == float("-inf")
    assert "snoozed" in s.reasons


def test_overdue_drives_score_and_is_capped():
    s = score_contact(_si(last_interaction_at=NOW - timedelta(days=300)), CFG, NOW)
    assert s.value == CFG.w_overdue * CFG.overdue_cap  # tier_weight loose = 1.0
    assert any("overdue" in r for r in s.reasons)


def test_never_contacted_is_treated_as_max_overdue():
    s = score_contact(_si(last_interaction_at=None), CFG, NOW)
    assert s.value == CFG.w_overdue * CFG.overdue_cap


def test_tier_multiplies():
    inner = score_contact(_si(last_interaction_at=NOW - timedelta(days=60), tier="inner"), CFG, NOW)
    loose = score_contact(_si(last_interaction_at=NOW - timedelta(days=60), tier="loose"), CFG, NOW)
    assert inner.value > loose.value


def test_pin_floors_the_score():
    s = score_contact(_si(last_interaction_at=NOW, pinned=True), CFG, NOW)
    assert s.value >= CFG.pin_floor
    assert "pinned" in s.reasons
