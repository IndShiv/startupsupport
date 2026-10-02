"""Pipeline board and list: columns, filters, moving startups between stages."""

import json
from datetime import timedelta

import pytest
from auditlog.models import LogEntry
from django.utils import timezone

from crm.models import Activity, Coach, Startup
from siteconfig.models import PipelineStage

pytestmark = pytest.mark.django_db

URL = "/staff/pipeline/"


@pytest.fixture
def coach_client(client, make_user):
    client.force_login(make_user("roeland", "Coach", coach=Coach.objects.get(first_name="Roeland")))
    return client


@pytest.fixture
def admin_client(client, make_user):
    client.force_login(make_user("boss", "Admin"))
    return client


def stage(name):
    return PipelineStage.objects.get(name=name)


def column(response, name):
    return next(c for c in response.context["columns"] if c["stage"].name == name)


def move(client, startup, target, json_response=True, **extra):
    headers = {"HTTP_ACCEPT": "application/json"} if json_response else {}
    return client.post(f"{URL}{startup.pk}/move/", {"stage": target.pk, **extra}, **headers)


def test_requires_staff(client, make_user, register):
    reg = register()
    assert client.get(URL).status_code == 302
    client.force_login(make_user("nobody"))
    assert client.get(URL).status_code == 403
    assert client.post(f"{URL}{reg.startup_id}/move/", {"stage": stage("Coaching").pk}).status_code == 403


def test_board_has_a_column_per_active_stage(admin_client, register):
    reg = register()
    response = admin_client.get(URL)
    names = [c["stage"].name for c in response.context["columns"]]
    assert names == list(PipelineStage.objects.filter(active=True).order_by("order").values_list("name", flat=True))
    assert [c["startup"].pk for c in column(response, "Registered")["cards"]] == [reg.startup_id]
    assert "drag" in response.content.decode().lower()


def test_closed_stages_collapsed_unless_requested(admin_client, register):
    reg = register()
    Startup.objects.filter(pk=reg.startup_id).update(stage=stage("Alumni"))
    col = column(admin_client.get(URL), "Alumni")
    assert col["collapsed"] and col["count"] == 1
    assert not column(admin_client.get(URL + "?closed=1"), "Alumni")["collapsed"]


def test_inactive_stage_still_shown_while_it_has_startups(admin_client, register):
    reg = register()
    old = PipelineStage.objects.create(name="Old stage", order=5, active=False)
    assert "Old stage" not in [c["stage"].name for c in admin_client.get(URL).context["columns"]]
    Startup.objects.filter(pk=reg.startup_id).update(stage=old)
    assert "Old stage" in [c["stage"].name for c in admin_client.get(URL).context["columns"]]


def test_coach_board_shows_own_caseload_by_default(coach_client, register):
    mine = register(student_number="100001", email="a@buas.nl")
    register(student_number="100002", email="b@buas.nl")
    Startup.objects.filter(pk=mine.startup_id).update(assigned_coach=Coach.objects.get(first_name="Roeland"))
    assert [c["startup"].pk for c in coach_client.get(URL).context["cards"]] == [mine.startup_id]
    assert len(coach_client.get(URL + "?scope=all").context["cards"]) == 2


def test_archived_startups_not_on_board(admin_client, register):
    reg = register()
    Startup.objects.filter(pk=reg.startup_id).update(archived_at=timezone.now())
    assert admin_client.get(URL).context["cards"] == []


def test_stale_flag(admin_client, register):
    reg = register()
    Startup.objects.filter(pk=reg.startup_id).update(created_at=timezone.now() - timedelta(weeks=10))
    assert admin_client.get(URL).context["cards"][0]["stale"]


def test_list_view(admin_client, register):
    reg = register()
    response = admin_client.get(URL + "?view=list")
    assert response.context["view"] == "list"
    assert f'id="lstage-{reg.startup_id}"' in response.content.decode()


# -- moving -------------------------------------------------------------------------------

def test_move_with_json(coach_client, register):
    reg = register()
    response = move(coach_client, reg.startup, stage("Coaching"))
    data = json.loads(response.content)
    assert response.status_code == 200 and data["ok"] and data["changed"]
    reg.startup.refresh_from_db()
    assert reg.startup.stage.name == "Coaching"
    activity = Activity.objects.get(startup=reg.startup, kind=Activity.Kind.STAGE)
    assert activity.author.username == "roeland"
    assert "“Registered” to “Coaching”" in activity.body
    entry = LogEntry.objects.get_for_object(reg.startup).filter(action=LogEntry.Action.UPDATE).first()
    assert "stage" in entry.changes_dict and entry.actor.username == "roeland"


def test_stage_change_does_not_count_as_activity(coach_client, register):
    reg = register()
    move(coach_client, reg.startup, stage("Coaching"))
    reg.startup.refresh_from_db()
    assert reg.startup.last_activity_at is None


def test_move_to_same_stage_is_a_no_op(coach_client, register):
    reg = register()
    data = json.loads(move(coach_client, reg.startup, stage("Registered")).content)
    assert data["ok"] and not data["changed"]
    assert not Activity.objects.exists()


def test_move_into_intake_stage_points_to_intake_page(coach_client, register):
    reg = register()
    data = json.loads(move(coach_client, reg.startup, stage("Intake done")).content)
    assert data["intake_url"] == f"/staff/intake/{reg.pk}/"
    assert "still open in the intake queue" in data["message"]


def test_move_without_javascript_redirects_back(coach_client, register):
    reg = register()
    response = move(coach_client, reg.startup, stage("Coaching"), json_response=False, next="/staff/pipeline/?view=list")
    assert response.status_code == 302 and response.url == "/staff/pipeline/?view=list"
    response = move(coach_client, reg.startup, stage("Alumni"), json_response=False, next="https://evil.example/")
    assert response.url == "/staff/pipeline/"


def test_move_to_unknown_stage(coach_client, register):
    reg = register()
    response = coach_client.post(f"{URL}{reg.startup_id}/move/", {"stage": "999"}, HTTP_ACCEPT="application/json")
    assert response.status_code == 400
    response = coach_client.post(f"{URL}{reg.startup_id}/move/", {"stage": "abc"}, HTTP_ACCEPT="application/json")
    assert response.status_code == 400


def test_cannot_move_archived_startup(coach_client, register):
    reg = register()
    Startup.objects.filter(pk=reg.startup_id).update(archived_at=timezone.now())
    assert move(coach_client, reg.startup, stage("Coaching")).status_code == 404


def test_move_requires_post(coach_client, register):
    reg = register()
    assert coach_client.get(f"{URL}{reg.startup_id}/move/").status_code == 405
