"""Unit tests for trading calendar calculations."""

from datetime import date, timedelta
from folioman_client.core.trading_calendar import (
    completed_trading_day,
    last_trading_day,
    trading_days,
    trading_days_between,
)


def test_last_trading_day_weekdays():
    # Wednesday remains Wednesday
    wed = date(2026, 4, 15)  # Wednesday
    assert last_trading_day(wed) == wed

    # Friday remains Friday
    fri = date(2026, 4, 17)  # Friday
    assert last_trading_day(fri) == fri


def test_last_trading_day_weekends():
    sat = date(2026, 4, 18)  # Saturday
    sun = date(2026, 4, 19)  # Sunday
    fri = date(2026, 4, 17)  # Prior Friday
    assert last_trading_day(sat) == fri
    assert last_trading_day(sun) == fri


def test_completed_trading_day():
    # On Wednesday, completed trading day is Tuesday
    wed = date(2026, 4, 15)
    tue = date(2026, 4, 14)
    assert completed_trading_day(wed) == tue

    # On Monday, completed trading day is prior Friday
    mon = date(2026, 4, 20)
    fri = date(2026, 4, 17)
    assert completed_trading_day(mon) == fri

    # On Sunday, completed trading day is prior Friday
    sun = date(2026, 4, 19)
    assert completed_trading_day(sun) == fri


def test_trading_days_between():
    mon = date(2026, 4, 13)
    fri = date(2026, 4, 17)
    # Tue, Wed, Thu, Fri = 4 weekdays in (mon, fri]
    assert trading_days_between(mon, fri) == 4

    # End <= Start returns 0
    assert trading_days_between(fri, mon) == 0
    assert trading_days_between(mon, mon) == 0

    # Over weekend: Fri to Mon (Mon is 1 weekday)
    next_mon = date(2026, 4, 20)
    assert trading_days_between(fri, next_mon) == 1


def test_trading_days_generator():
    start = date(2026, 4, 16)  # Thursday
    end = date(2026, 4, 21)    # Tuesday
    # Days should be Thu 16, Fri 17, Mon 20, Tue 21 (4 weekdays)
    days = list(trading_days(start, end))
    assert days == [
        date(2026, 4, 16),
        date(2026, 4, 17),
        date(2026, 4, 20),
        date(2026, 4, 21),
    ]
