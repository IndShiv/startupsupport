"""Intake queue: permissions, ordering, deadlines and recording intakes."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from crm.intake import advance_stage, urgency
from crm.models import Activity, Coach, Notification, Registration
from crm.workdays import add_working_days
from siteconfig.models import ClosureDay, PipelineStage, StudyYear

pytestmark = pytest.mark.django_db

QUEUE = "/staff/intake/"


def detail(reg):
    return f"/staff/intake/{reg.pk}/"


@pytest.fixture
def coach_user(make_user):
    return make_user("roeland", "Coach", coach=Coach.objects.get(first_name="Roeland"))


@pytest.fixture
def coach_client(client, coach_user):
    client.force_login(coach_user)
    return client


# -- permissions ----------------------------------------------------------------------

def test_anonymous_is_sent_to_login(client, reference):
    response = client.get(QUEUE)
    assert response.status_code == 302 and response.url.startswith("/staff/login/")


def test_user_without_role_is_refused(client, make_user):
    client.force_login(make_user("someone"))
    assert client.get(QUEUE).status_code == 403


@pytest.mark.parametrize("group", ["Coach", "Admin"])
def test_staff_can_open_queue(client, make_user, group):
    client.force_login(make_user("staffer", group))
    assert client.get(QUEUE).status_code == 200


def test_login_page_works(client, make_user):
    make_user("coachy", "Coach")
    response = client.post("/staff/login/", {"username": "coachy", "password": "pw"})
    assert response.status_code == 302
    assert client.get(QUEUE).status_code == 200


# -- urgency and ordering -------------------------------------------------------------

@pytest.mark.parametrize("deadline, level, days", [
    (date(2026, 9, 30), "overdue", -2),   # Wed; today Fri 2 Oct
    (date(2026, 10, 2), "due-soon", 0),
    (date(2026, 10, 6), "due-soon", 2),
    (date(2026, 10, 7), "ok", 3),
])
def test_urgency_levels(deadline, level, days):
    result = urgency(Registration(intake_deadline=deadline), today=date(2026, 10, 2), due_soon=2)
    assert (result.level, result.days_left) == (level, days)


def test_urgency_labels():
    assert urgency(Registration(intake_deadline=date(2026, 9, 30)), date(2026, 10, 2), 2).label == "2 working days overdue"
    assert urgency(Registration(intake_deadline=date(2026, 10, 2)), date(2026, 10, 2), 2).label == "Due today"
    assert urgency(Registration(intake_deadline=date(2026, 10, 5)), date(2026, 10, 2), 2).label == "1 working day left"


def test_queue_sorted_by_days_remaining_and_highlighted(coach_client, register):
    today = timezone.localdate()
    later = register(student_number="100001", email="a@buas.nl")
    overdue = register(student_number="100002", email="b@buas.nl")
    soon = register(student_number="100003", email="c@buas.nl")
    Registration.objects.filter(pk=overdue.pk).update(intake_deadline=today - timedelta(days=7))
    Registration.objects.filter(pk=soon.pk).update(intake_deadline=add_working_days(today, 1))
    Registration.objects.filter(pk=later.pk).update(intake_deadline=add_working_days(today, 8))

    response = coach_client.get(QUEUE)
    rows = response.context["rows"]
    assert [r["registration"].pk for r in rows] == [overdue.pk, soon.pk, later.pk]
    assert [r["urgency"].level for r in rows] == ["overdue", "due-soon", "ok"]
    html = response.content.decode()
    assert "row-overdue" in html and "row-due-soon" in html
    assert "1 registration is overdue" in html


def test_scheduled_and_done_leave_the_waiting_tab(coach_client, register):
    waiting, scheduled, done = (register(student_number=f"20000{i}", email=f"x{i}@buas.nl") for i in range(3))
    today = timezone.localdate()
    Registration.objects.filter(pk=scheduled.pk).update(intake_scheduled_on=today)
    Registration.objects.filter(pk=done.pk).update(intake_scheduled_on=today, intake_held_on=today)
    response = coach_client.get(QUEUE)
    assert [r["registration"].pk for r in response.context["rows"]] == [waiting.pk]
    assert [r["registration"].pk for r in coach_client.get(QUEUE + "?tab=scheduled").context["rows"]] == [scheduled.pk]
    assert [r["registration"].pk for r in coach_client.get(QUEUE + "?tab=done").context["rows"]] == [done.pk]


def test_only_mine_filter(coach_client, register, coach_user):
    mine = register(student_number="300001", email="m@buas.nl", preferred_coach=str(coach_user.coach.pk))
    register(student_number="300002", email="n@buas.nl")
    rows = coach_client.get(QUEUE + "?mine=1").context["rows"]
    assert [r["registration"].pk for r in rows] == [mine.pk]


# -- scheduling and holding intakes ----------------------------------------------------

def test_schedule_intake(coach_client, register, coach_user):
    reg = register()
    coach = coach_user.coach
    today = timezone.localdate()
    response = coach_client.post(detail(reg), {
        "action": "schedule", "schedule-scheduled_on": today.isoformat(),
        "schedule-planned_at": f"{(today + timedelta(days=3)).isoformat()}T14:00",
        "schedule-coach": coach.pk, "schedule-assign_coach": "on",
    })
    assert response.status_code == 302
    reg.refresh_from_db()
    assert reg.intake_scheduled_on == today
    assert reg.intake_coach == coach
    assert timezone.localtime(reg.intake_planned_at).hour == 14
    assert reg.startup.assigned_coach == coach
    assert reg.startup.stage.name == "Intake scheduled"
    assert not Registration.objects.awaiting_intake().exists()


def test_schedule_date_cannot_be_in_future(coach_client, register, coach_user):
    reg = register()
    response = coach_client.post(detail(reg), {
        "action": "schedule", "schedule-scheduled_on": (timezone.localdate() + timedelta(days=1)).isoformat(),
        "schedule-coach": coach_user.coach.pk,
    })
    assert response.status_code == 200
    assert "cannot be in the future" in response.content.decode()
    reg.refresh_from_db()
    assert reg.intake_scheduled_on is None


def test_record_intake_held(coach_client, register, coach_user):
    reg = register()
    coach = coach_user.coach
    other = Coach.objects.get(first_name="Tijs")
    today = timezone.localdate()
    response = coach_client.post(detail(reg), {
        "action": "held", "held-held_on": today.isoformat(), "held-coach": coach.pk,
        "held-assigned_coach": other.pk, "held-note": "Great energy, next step customer interviews.",
    })
    assert response.status_code == 302
    reg.refresh_from_db()
    assert reg.intake_held_on == today
    assert reg.intake_scheduled_on == today  # clock stopped on the day it was held
    assert reg.intake_coach == coach
    assert reg.startup.assigned_coach == other
    assert reg.startup.stage.name == "Intake done"
    activity = Activity.objects.get(startup=reg.startup)
    assert activity.kind == "intake" and activity.author == coach_user
    assert "customer interviews" in activity.body


def test_stage_never_moves_backwards(register):
    reg = register()
    startup = reg.startup
    startup.stage = PipelineStage.objects.get(name="Coaching")
    advance_stage(startup, scheduled=True)
    assert startup.stage.name == "Coaching"


def test_graduation_track_same_domain_coach_needs_confirmation(coach_client, register):
    games_coach = Coach.objects.get(first_name="Hans")  # Games & Media
    reg = register(
        study_year=StudyYear.objects.get(is_graduation_track=True).pk, grad_approval="yes",
        grad_topic="Topic", grad_supervisor="Dr. X", grad_hand_in_date=(timezone.localdate() + timedelta(days=90)).isoformat(),
    )
    data = {"action": "held", "held-held_on": timezone.localdate().isoformat(), "held-coach": games_coach.pk, "held-assigned_coach": games_coach.pk}
    response = coach_client.post(detail(reg), data)
    assert response.status_code == 200
    assert "from the student&#x27;s own domain" in response.content.decode()
    assert "same domain as student" in response.content.decode()  # flagged in the coach dropdown
    reg.refresh_from_db()
    assert reg.intake_held_on is None

    response = coach_client.post(detail(reg), dict(data, **{"held-confirm_domain": "on"}))
    assert response.status_code == 302
    reg.refresh_from_db()
    assert reg.startup.assigned_coach == games_coach


def test_coach_dropdown_shows_caseload(coach_client, register):
    reg = register()
    content = coach_client.get(detail(reg)).content.decode()
    assert "Roeland Bottema · 0 active startups" in content


# -- deadlines -------------------------------------------------------------------------

def test_closure_day_moves_open_deadlines(register):
    reg = register()
    old = reg.intake_deadline
    ClosureDay.objects.create(date=add_working_days(timezone.localdate(), 2), name="BUas closed")
    reg.refresh_from_db()
    assert reg.intake_deadline == add_working_days(old, 1)


def test_closure_day_does_not_touch_scheduled_registrations(register):
    reg = register()
    Registration.objects.filter(pk=reg.pk).update(intake_scheduled_on=timezone.localdate())
    old = reg.intake_deadline
    ClosureDay.objects.create(date=add_working_days(timezone.localdate(), 2), name="BUas closed")
    reg.refresh_from_db()
    assert reg.intake_deadline == old


# -- notifications ---------------------------------------------------------------------

def test_notifications_page_and_mark_read(client, make_user):
    admin = make_user("boss", "Admin")
    Notification.objects.create(user=admin, message="New registration: Sam", url="/staff/intake/")
    client.force_login(admin)
    assert "New registration: Sam" in client.get("/staff/notifications/").content.decode()
    assert 'class="badge"' in client.get(QUEUE).content.decode()
    client.post("/staff/notifications/read/", {"next": "https://evil.example/"})
    assert not Notification.objects.filter(read_at__isnull=True).exists()


def test_notification_open_marks_read_and_redirects(client, make_user):
    admin = make_user("boss", "Admin")
    item = Notification.objects.create(user=admin, message="x", url="/staff/intake/")
    client.force_login(admin)
    response = client.get(f"/staff/notifications/{item.pk}/")
    assert response.url == "/staff/intake/"
    item.refresh_from_db()
    assert item.read_at is not None


def test_cannot_open_someone_elses_notification(client, make_user):
    admin, other = make_user("boss", "Admin"), make_user("other", "Admin")
    item = Notification.objects.create(user=other, message="x", url="/staff/intake/")
    client.force_login(admin)
    assert client.get(f"/staff/notifications/{item.pk}/").status_code == 404
