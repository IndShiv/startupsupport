"""Dashboard figures."""

from datetime import date, datetime, time, timedelta

import pytest
from django.utils import timezone

from crm import dashboard
from crm.models import Activity, Coach, GraduationTrack, Registration, Startup
from siteconfig.models import Domain, PipelineStage

pytestmark = pytest.mark.django_db


def at(day):
    return timezone.make_aware(datetime.combine(day, time(12)))


@pytest.fixture
def reg(register):
    """Create a registration submitted on a given day with a given deadline/schedule."""
    counter = iter(range(100000, 199999))

    def build(submitted, deadline=None, scheduled=None, **form):
        n = next(counter)
        r = register(student_number=str(n), email=f"s{n}@buas.nl", **form)
        Registration.objects.filter(pk=r.pk).update(
            submitted_at=at(submitted), intake_deadline=deadline or submitted + timedelta(days=14), intake_scheduled_on=scheduled,
        )
        r.refresh_from_db()
        return r

    return build


# -- periods ------------------------------------------------------------------------------

@pytest.mark.parametrize("today, start", [(date(2026, 10, 5), date(2026, 9, 1)), (date(2026, 3, 1), date(2025, 9, 1)), (date(2026, 9, 1), date(2026, 9, 1))])
def test_academic_year_starts_1_september(reference, today, start):
    assert dashboard.get_period("ay", today).start == start


def test_month_periods_and_unknown_key(reference):
    today = date(2026, 10, 5)
    assert dashboard.get_period("3m", today).start == date(2026, 8, 1)
    assert dashboard.get_period("12m", today).start == date(2025, 11, 1)
    assert dashboard.get_period("nonsense", today).key == dashboard.DEFAULT_PERIOD


def test_months_cross_year_boundary(reference):
    period = dashboard.get_period("3m", date(2026, 1, 15))
    assert dashboard.months(period) == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1)]


# -- turnaround ----------------------------------------------------------------------------

def test_turnaround_counts_only_decided_registrations(reg):
    today = timezone.localdate()
    d = today - timedelta(days=30)
    reg(d, deadline=d + timedelta(days=14), scheduled=d + timedelta(days=3))     # on time
    reg(d, deadline=d + timedelta(days=14), scheduled=d + timedelta(days=14))    # on the deadline: on time
    reg(d, deadline=d + timedelta(days=14), scheduled=d + timedelta(days=20))    # late
    reg(d, deadline=today - timedelta(days=1))                                     # still waiting, overdue: late
    reg(today, deadline=today + timedelta(days=14))                                # still within deadline: not counted
    result = dashboard.turnaround(Registration.objects.all(), today)
    assert result == {"total": 4, "on_time": 2, "late": 2, "pct": 50}


def test_turnaround_without_data(reference):
    assert dashboard.turnaround(Registration.objects.none(), timezone.localdate())["pct"] is None


def test_registrations_per_month_includes_empty_months(reg):
    today = timezone.localdate()
    this_month = today.replace(day=1)
    reg(this_month)
    reg(this_month)
    period = dashboard.get_period("3m", today)
    rows = dashboard.registrations_per_month(period)
    assert [r["count"] for r in rows] == [0, 0, 2]
    assert rows[-1]["pct_of_max"] == 100


def test_kpis(reg):
    today = timezone.localdate()
    reg(today - timedelta(days=3), deadline=today - timedelta(days=1))   # waiting and overdue
    reg(today, deadline=today + timedelta(days=10))                      # waiting
    k = dashboard.kpis(dashboard.get_period("12m", today))
    assert (k["registrations"], k["waiting"], k["overdue"], k["active_startups"]) == (2, 2, 1, 2)


# -- breakdowns ----------------------------------------------------------------------------

def test_per_stage_excludes_archived_and_marks_closed(reg):
    today = timezone.localdate()
    a, b, c = reg(today), reg(today), reg(today)
    Startup.objects.filter(pk=b.startup_id).update(stage=PipelineStage.objects.get(name="Alumni"))
    Startup.objects.filter(pk=c.startup_id).update(archived_at=timezone.now())
    rows = {r["label"]: r for r in dashboard.per_stage()}
    assert rows["Registered"]["count"] == 1
    assert rows["Alumni"]["count"] == 1 and rows["Alumni"]["closed"]


def test_per_domain_respects_period(reg):
    today = timezone.localdate()
    tourism = Domain.objects.get(name="Tourism").pk
    reg(today, domain=tourism)
    reg(today - timedelta(days=400), domain=tourism)
    rows = {r["label"]: r["count"] for r in dashboard.per_domain(dashboard.get_period("3m", today))}
    assert rows["Tourism"] == 1


def test_caseload_sorted_by_size(reg):
    today = timezone.localdate()
    tijs, joyce = Coach.objects.get(first_name="Tijs"), Coach.objects.get(first_name="Joyce")
    for r in (reg(today), reg(today)):
        Startup.objects.filter(pk=r.startup_id).update(assigned_coach=tijs)
    Startup.objects.filter(pk=reg(today).startup_id).update(assigned_coach=joyce)
    rows = dashboard.caseload()
    assert (rows[0]["label"], rows[0]["count"]) == ("Tijs van Es", 2)
    assert next(r for r in rows if r["label"] == "Joyce Ridderhof")["count"] == 1


def test_graduation_lists(register, graduation_data):
    today = timezone.localdate()
    soon = register(**graduation_data(student_number="200001", email="g1@buas.nl", grad_approval="not_yet",
                                      grad_hand_in_date=(today + timedelta(days=20)).isoformat()))
    register(**graduation_data(student_number="200002", email="g2@buas.nl", grad_approval="yes",
                               grad_hand_in_date=(today + timedelta(days=200)).isoformat()))
    late = register(**graduation_data(student_number="200003", email="g3@buas.nl", grad_approval="yes",
                                      grad_hand_in_date=(today + timedelta(days=5)).isoformat()))
    GraduationTrack.objects.filter(registration=late).update(hand_in_date=today - timedelta(days=3))
    g = dashboard.graduation(today)
    assert [t.registration_id for t in g["approval_missing"]] == [soon.pk]
    assert [t.registration_id for t in g["upcoming"]] == [soon.pk]
    assert [t.registration_id for t in g["overdue_hand_in"]] == [late.pk]


def test_graduation_lists_skip_closed_startups(register, graduation_data):
    r = register(**graduation_data(grad_approval="not_yet"))
    Startup.objects.filter(pk=r.startup_id).update(stage=PipelineStage.objects.get(name="Stopped"))
    assert dashboard.graduation(timezone.localdate())["approval_missing"] == []


def test_inactive_startups(reg):
    today = timezone.localdate()
    quiet, busy, stopped, fresh = reg(today), reg(today), reg(today), reg(today)
    old = timezone.now() - timedelta(weeks=10)
    Startup.objects.filter(pk__in=[quiet.startup_id, busy.startup_id, stopped.startup_id]).update(created_at=old)
    Startup.objects.filter(pk=stopped.startup_id).update(stage=PipelineStage.objects.get(name="Stopped"))
    Activity.objects.create(startup=busy.startup, kind="meeting", body="Met")
    Activity.objects.create(startup=quiet.startup, kind="stage", body="Moved")  # bookkeeping doesn't count
    result = dashboard.inactive_startups()
    assert [s.pk for s in result["startups"]] == [quiet.startup_id]
    assert result["count"] == 1


# -- the page --------------------------------------------------------------------------------

def test_dashboard_is_staff_home(client, make_user, reg):
    reg(timezone.localdate())
    assert client.get("/staff/dashboard/").status_code == 302
    client.force_login(make_user("nobody"))
    assert client.get("/staff/dashboard/").status_code == 403
    client.force_login(make_user("coachy", "Coach"))
    assert client.get("/staff/").url == "/staff/dashboard/"
    for period in ["3m", "6m", "12m", "ay", "all", "bogus"]:
        response = client.get(f"/staff/dashboard/?period={period}")
        assert response.status_code == 200
    content = client.get("/staff/dashboard/").content.decode()
    assert "Registrations per month" in content and "Show as table" in content


def test_quiet_filter_matches_dashboard(client, make_user, reg):
    today = timezone.localdate()
    a, b = reg(today), reg(today)
    Startup.objects.filter(pk=a.startup_id).update(created_at=timezone.now() - timedelta(weeks=10))
    client.force_login(make_user("boss", "Admin"))
    ids = {s.pk for s in client.get("/staff/startups/?scope=all&quiet=on").context["page"].object_list}
    assert ids == {s.pk for s in dashboard.inactive_startups()["startups"]} == {a.startup_id}
