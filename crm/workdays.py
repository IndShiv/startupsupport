"""Working-day arithmetic for the intake promise.

A working day is Monday–Friday that is not a Dutch public holiday and not a
BUas closure day (managed in the admin). Counting starts on the working day
*after* registration: a registration on Monday with a 10-day promise is due
on Monday two weeks later.
"""

from datetime import date, timedelta
from functools import lru_cache

import holidays

from siteconfig.models import ClosureDay


@lru_cache(maxsize=16)
def _public_holidays(year):
    return set(holidays.NL(years=year).keys())


def non_working_days(start, end):
    closures = set(ClosureDay.objects.filter(date__range=(start, end)).values_list("date", flat=True))
    public = set()
    for year in range(start.year, end.year + 1):
        public |= _public_holidays(year)
    return closures | public


def is_working_day(day, extra_closed=frozenset()):
    return day.weekday() < 5 and day not in extra_closed


def add_working_days(start: date, days: int) -> date:
    # Fetch closures once for a generous window (days * 2 + 30 covers holidays and weekends).
    closed = non_working_days(start, start + timedelta(days=days * 2 + 30))
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if is_working_day(current, closed):
            remaining -= 1
    return current


def working_days_between(start: date, end: date) -> int:
    """Working days from start (exclusive) to end (inclusive); negative if end is before start."""
    if end == start:
        return 0
    sign = 1
    if end < start:
        start, end, sign = end, start, -1
    closed = non_working_days(start, end)
    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if is_working_day(current, closed):
            count += 1
    return sign * count
