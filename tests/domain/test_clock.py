from datetime import UTC, datetime, timedelta

from whodex.domain.clock import FixedClock, SystemClock


def test_fixed_clock_returns_its_time():
    t = datetime(2026, 6, 1, tzinfo=UTC)
    assert FixedClock(t).now() == t


def test_fixed_clock_advance():
    t = datetime(2026, 6, 1, tzinfo=UTC)
    clock = FixedClock(t)
    clock.advance(timedelta(days=2))
    assert clock.now() == t + timedelta(days=2)


def test_system_clock_is_tz_aware_utc():
    assert SystemClock().now().tzinfo == UTC
