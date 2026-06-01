from datetime import UTC, datetime, timedelta

from whodex.domain.enums import Staleness
from whodex.engine.freshness import FreshnessConfig, staleness

NOW = datetime(2026, 3, 1, tzinfo=UTC)
CFG = FreshnessConfig(ttl_days={"job.title": 90, "email": 365, "birthday": 0}, grace_factor=2.0)


def test_fresh_within_ttl():
    assert staleness("job.title", NOW - timedelta(days=30), CFG, NOW) == Staleness.fresh


def test_stale_past_ttl_within_grace():
    assert staleness("job.title", NOW - timedelta(days=120), CFG, NOW) == Staleness.stale


def test_expired_past_grace():
    assert staleness("job.title", NOW - timedelta(days=200), CFG, NOW) == Staleness.expired


def test_ttl_zero_never_stale():
    assert staleness("birthday", NOW - timedelta(days=9999), CFG, NOW) == Staleness.fresh


def test_unconfigured_field_defaults_fresh():
    assert staleness("tags", NOW - timedelta(days=9999), CFG, NOW) == Staleness.fresh
