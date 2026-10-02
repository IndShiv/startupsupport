from datetime import date

import pytest

from crm.workdays import add_working_days, working_days_between
from siteconfig.models import ClosureDay

pytestmark = pytest.mark.django_db


def test_ten_working_days_from_monday_is_monday_two_weeks_later():
    assert add_working_days(date(2026, 9, 14), 10) == date(2026, 9, 28)


def test_weekend_registration_starts_counting_on_monday():
    # Saturday 19 Sep 2026: Mon 21 is day 1, Fri 2 Oct is day 10.
    assert add_working_days(date(2026, 9, 19), 10) == date(2026, 10, 2)
    assert add_working_days(date(2026, 9, 20), 10) == date(2026, 10, 2)


def test_skips_dutch_public_holidays():
    # Koningsdag is Monday 27 April 2026.
    assert add_working_days(date(2026, 4, 24), 1) == date(2026, 4, 28)
    # Christmas 2026: Fri 25 Dec and Sat 26 Dec; Thu 24 Dec + 1 = Mon 28 Dec.
    assert add_working_days(date(2026, 12, 24), 1) == date(2026, 12, 28)
    # Easter 2026: Good Friday 3 Apr and Easter Monday 6 Apr.
    assert add_working_days(date(2026, 4, 2), 1) == date(2026, 4, 7)


def test_skips_admin_closure_days():
    ClosureDay.objects.create(date=date(2026, 12, 28), name="BUas closed")
    ClosureDay.objects.create(date=date(2026, 12, 29), name="BUas closed")
    assert add_working_days(date(2026, 12, 24), 1) == date(2026, 12, 30)


def test_working_days_between():
    assert working_days_between(date(2026, 9, 14), date(2026, 9, 28)) == 10
    assert working_days_between(date(2026, 9, 28), date(2026, 9, 14)) == -10
    assert working_days_between(date(2026, 10, 2), date(2026, 10, 2)) == 0
    # Friday to Monday is one working day.
    assert working_days_between(date(2026, 10, 2), date(2026, 10, 5)) == 1
