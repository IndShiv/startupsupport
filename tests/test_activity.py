"""Activity log entries and follow-ups."""

from datetime import timedelta

import pytest
from django.utils import timezone

from crm.models import Activity, Coach, FollowUp, Startup
from staff.context_processors import end_of_week

pytestmark = pytest.mark.django_db


@pytest.fixture
def roeland(make_user):
    return make_user("roeland", "Coach", coach=Coach.objects.get(first_name="Roeland"))


@pytest.fixture
def coach_client(client, roeland):
    client.force_login(roeland)
    return client


@pytest.fixture
def startup(register, roeland):
    reg = register()
    Startup.objects.filter(pk=reg.startup_id).update(assigned_coach=roeland.coach)
    return Startup.objects.get(pk=reg.startup_id)


def add(client, startup, **data):
    payload = {"activity-kind": "note", "activity-date": timezone.localdate().isoformat(), "activity-body": "Text"}
    payload.update({f"activity-{k}": v for k, v in data.items()})
    return client.post(f"/staff/startups/{startup.pk}/activity/", payload)


# -- activity log -----------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["note", "meeting", "email", "event", "referral"])
def test_add_each_kind(coach_client, startup, roeland, kind):
    response = add(coach_client, startup, kind=kind, body=f"A {kind}")
    assert response.status_code == 302
    activity = Activity.objects.get(startup=startup, kind=kind)
    assert activity.author == roeland and activity.body == f"A {kind}"
    startup.refresh_from_db()
    assert startup.last_activity_at is not None


def test_system_kinds_cannot_be_added_by_hand(coach_client, startup):
    response = add(coach_client, startup, kind="stage")
    assert response.status_code == 200
    assert not Activity.objects.exists()


def test_future_dates_are_refused(coach_client, startup):
    response = add(coach_client, startup, date=(timezone.localdate() + timedelta(days=3)).isoformat())
    assert response.status_code == 200
    assert "Plan future meetings as a follow-up" in response.content.decode()
    assert "Text" in response.content.decode()  # typed text kept


def test_activity_with_follow_up(coach_client, startup, roeland):
    due = timezone.localdate() + timedelta(days=4)
    add(coach_client, startup, kind="meeting", follow_up_title="Check interviews", follow_up_due=due.isoformat())
    follow_up = FollowUp.objects.get()
    assert follow_up.startup == startup and follow_up.due_date == due
    assert follow_up.assigned_to == roeland  # the startup's coach
    assert follow_up.created_by == roeland


def test_follow_up_needs_both_title_and_date(coach_client, startup):
    assert add(coach_client, startup, follow_up_title="Something").status_code == 200
    assert not Activity.objects.exists()


def test_coach_cannot_mark_admin_only(coach_client, startup):
    add(coach_client, startup, admin_only="on")
    assert Activity.objects.get().admin_only is False


def test_admin_can_mark_admin_only(client, make_user, startup):
    client.force_login(make_user("boss", "Admin"))
    add(client, startup, admin_only="on")
    assert Activity.objects.get().admin_only is True


def test_author_can_edit_and_delete(coach_client, startup):
    add(coach_client, startup)
    activity = Activity.objects.get()
    response = coach_client.post(f"/staff/activity/{activity.pk}/edit/", {"kind": "email", "date": activity.date.isoformat(), "body": "Changed"})
    assert response.status_code == 302
    activity.refresh_from_db()
    assert activity.kind == "email" and activity.body == "Changed"
    coach_client.post(f"/staff/activity/{activity.pk}/delete/")
    assert not Activity.objects.exists()


def test_other_coach_cannot_edit(client, make_user, startup, roeland):
    activity = Activity.objects.create(startup=startup, kind="note", body="Mine", author=roeland)
    client.force_login(make_user("other", "Coach"))
    assert client.get(f"/staff/activity/{activity.pk}/edit/").status_code == 403
    assert client.post(f"/staff/activity/{activity.pk}/delete/").status_code == 403


def test_admin_can_edit_anyones_entry(client, make_user, startup, roeland):
    activity = Activity.objects.create(startup=startup, kind="note", body="Mine", author=roeland)
    client.force_login(make_user("boss", "Admin"))
    assert client.get(f"/staff/activity/{activity.pk}/edit/").status_code == 200


@pytest.mark.parametrize("kind", ["intake", "stage"])
def test_system_entries_are_read_only(client, make_user, startup, kind):
    activity = Activity.objects.create(startup=startup, kind=kind, body="System")
    client.force_login(make_user("boss", "Admin"))
    assert client.get(f"/staff/activity/{activity.pk}/edit/").status_code == 403


def test_log_shows_entries_newest_first(coach_client, startup):
    Activity.objects.create(startup=startup, kind="note", body="Old", date=timezone.localdate() - timedelta(days=10))
    Activity.objects.create(startup=startup, kind="meeting", body="New", date=timezone.localdate())
    entries = [a for a, _ in coach_client.get(f"/staff/startups/{startup.pk}/").context["activities"]]
    assert [a.body for a in entries] == ["New", "Old"]


# -- follow-ups -------------------------------------------------------------------------------

def make(startup, days, user=None, **kw):
    return FollowUp.objects.create(startup=startup, title=kw.pop("title", f"in {days}"), due_date=timezone.localdate() + timedelta(days=days), assigned_to=user, **kw)


def titles(response):
    return {f.title for f in response.context["items"]}


def test_my_week(coach_client, startup, roeland, make_user):
    week_end = end_of_week()
    days_to_end = (week_end - timezone.localdate()).days
    make(startup, -3, roeland, title="overdue")
    make(startup, days_to_end, roeland, title="end of week")
    make(startup, days_to_end + 1, roeland, title="next week")
    make(startup, 0, make_user("other", "Coach"), title="someone else's")
    make(startup, 0, None, title="unassigned on my startup")
    make(startup, -1, roeland, title="done", done_at=timezone.now())
    response = coach_client.get("/staff/follow-ups/")
    assert titles(response) == {"overdue", "end of week", "unassigned on my startup"}
    assert response.context["overdue"] == 1
    assert titles(coach_client.get("/staff/follow-ups/?tab=upcoming")) == {"next week"}
    assert titles(coach_client.get("/staff/follow-ups/?tab=done")) == {"done"}
    assert "someone else's" in titles(coach_client.get("/staff/follow-ups/?scope=all"))


def test_menu_badge_counts_due_this_week(coach_client, startup, roeland):
    make(startup, -1, roeland)
    make(startup, 30, roeland)
    assert '<span class="nav-badge"' in coach_client.get("/staff/follow-ups/").content.decode()
    assert coach_client.get("/staff/follow-ups/").context["my_followups_due"]() == 1


def test_unassigned_scope_is_admin_only(client, make_user, startup):
    make(startup, 1, None, title="nobody")
    client.force_login(make_user("coachy", "Coach"))
    assert client.get("/staff/follow-ups/?scope=unassigned").context["scope"] == "mine"
    client.force_login(make_user("boss", "Admin"))
    assert titles(client.get("/staff/follow-ups/?scope=unassigned")) == {"nobody"}


def test_automatic_approval_reminder_shows_for_the_coach(coach_client, register, graduation_data, roeland):
    reg = register(**graduation_data(grad_approval="not_yet"))
    Startup.objects.filter(pk=reg.startup_id).update(assigned_coach=roeland.coach)
    follow_up = FollowUp.objects.get(auto_reason="graduation_approval_missing")
    assert follow_up.assigned_to is None
    assert follow_up in FollowUp.objects.for_user(roeland)


def test_done_reopen_and_snooze(coach_client, startup, roeland):
    f = make(startup, -2, roeland)
    coach_client.post(f"/staff/follow-ups/{f.pk}/done/")
    f.refresh_from_db()
    assert f.done_at is not None
    coach_client.post(f"/staff/follow-ups/{f.pk}/done/")
    f.refresh_from_db()
    assert f.done_at is None
    coach_client.post(f"/staff/follow-ups/{f.pk}/snooze/")
    f.refresh_from_db()
    assert f.due_date == timezone.localdate() + timedelta(days=7)  # overdue items move a week from today


def test_create_from_student_page(coach_client, startup, roeland):
    student = startup.founders.first()
    response = coach_client.post(f"/staff/follow-ups/new/?student={student.pk}&next=/staff/students/{student.pk}/",
                                 {"title": "Call about funding", "due_date": (timezone.localdate() + timedelta(days=2)).isoformat(),
                                  "assigned_to": roeland.pk, "notes": ""})
    assert response.status_code == 302 and response.url == f"/staff/students/{student.pk}/"
    assert FollowUp.objects.get().student == student


def test_edit_and_reassign(coach_client, startup, make_user):
    other = make_user("other", "Coach")
    f = make(startup, 3)
    response = coach_client.post(f"/staff/follow-ups/{f.pk}/edit/", {"title": "Renamed", "due_date": f.due_date.isoformat(), "assigned_to": other.pk, "notes": "n"})
    assert response.status_code == 302
    f.refresh_from_db()
    assert f.title == "Renamed" and f.assigned_to == other


def test_follow_up_redirect_is_safe(coach_client, startup, roeland):
    f = make(startup, 1, roeland)
    response = coach_client.post(f"/staff/follow-ups/{f.pk}/done/", {"next": "https://evil.example/"})
    assert response.url == "/staff/follow-ups/"
