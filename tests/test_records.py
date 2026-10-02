"""Student and startup records: lists, filters, editing, archiving, founders, merging, walk-ins."""

from datetime import timedelta

import pytest
from auditlog.models import LogEntry
from django.core import mail
from django.utils import timezone

from crm.models import Activity, Coach, Founder, FollowUp, GraduationTrack, Registration, Startup, Student, Tag
from siteconfig.models import Domain, PipelineStage, StudyYear

pytestmark = pytest.mark.django_db


@pytest.fixture
def coach(reference):
    return Coach.objects.get(first_name="Roeland")


@pytest.fixture
def coach_client(client, make_user, coach):
    client.force_login(make_user("roeland", "Coach", coach=coach))
    return client


@pytest.fixture
def admin_client(client, make_user):
    client.force_login(make_user("boss", "Admin"))
    return client


def ids(response, key="page"):
    return {obj.pk for obj in response.context[key].object_list}


@pytest.fixture
def three(register, coach):
    """Three registrations; the first startup is in Roeland's caseload."""
    a = register(student_number="100001", email="a@buas.nl", first_name="Anna")
    b = register(student_number="100002", email="b@buas.nl", first_name="Bram", has_paying_customers="yes")
    c = register(student_number="100003", email="c@buas.nl", first_name="Chloe", domain=Domain.objects.get(name="Tourism").pk)
    Startup.objects.filter(pk=a.startup_id).update(assigned_coach=coach)
    return a, b, c


# -- lists and filters -------------------------------------------------------------------

def test_coach_sees_own_caseload_by_default(coach_client, three):
    a, b, c = three
    assert ids(coach_client.get("/staff/startups/")) == {a.startup_id}
    assert ids(coach_client.get("/staff/startups/?scope=all")) == {a.startup_id, b.startup_id, c.startup_id}
    assert ids(coach_client.get("/staff/students/")) == {a.student_id}


def test_admin_without_coach_profile_sees_everyone(admin_client, three):
    assert len(ids(admin_client.get("/staff/startups/"))) == 3


@pytest.mark.parametrize("query, expected", [
    ("paying=yes", ["b"]),
    ("paying=no", ["a", "c"]),
    ("q=chloe", ["c"]),
    ("q=100002", ["b"]),
    ("domain={tourism}", ["c"]),
    ("coach_filter={coach}", ["a"]),
    ("no_coach=on", ["b", "c"]),
    ("graduation=yes", []),
])
def test_startup_filters(admin_client, three, coach, query, expected):
    by_name = dict(zip("abc", three))
    query = query.format(tourism=Domain.objects.get(name="Tourism").pk, coach=coach.pk)
    got = ids(admin_client.get(f"/staff/startups/?scope=all&{query}"))
    assert got == {by_name[k].startup_id for k in expected}


def test_unknown_paying_filter(admin_client, three):
    a, _, _ = three
    Startup.objects.filter(pk=a.startup_id).update(has_paying_customers=None)
    assert ids(admin_client.get("/staff/startups/?paying=unknown")) == {a.startup_id}


def test_tag_filter_requires_all_tags(admin_client, three):
    a, b, _ = three
    t1, t2 = Tag.objects.create(name="tech"), Tag.objects.create(name="impact")
    a.startup.tags.add(t1, t2)
    b.startup.tags.add(t1)
    assert ids(admin_client.get(f"/staff/startups/?tags={t1.pk}")) == {a.startup_id, b.startup_id}
    assert ids(admin_client.get(f"/staff/startups/?tags={t1.pk}&tags={t2.pk}")) == {a.startup_id}


def test_stage_and_graduation_filters(admin_client, graduation_data, register):
    reg = register(**{k: v for k, v in graduation_data(grad_approval="not_yet").items()})
    register(student_number="100009", email="z@buas.nl")
    stage = PipelineStage.initial()
    assert reg.startup_id in ids(admin_client.get(f"/staff/startups/?stage={stage.pk}"))
    assert ids(admin_client.get("/staff/startups/?graduation=approval_missing")) == {reg.startup_id}
    assert ids(admin_client.get("/staff/students/?graduation=approval_missing")) == {reg.student_id}


def test_archived_records_hidden_by_default(admin_client, three):
    a, _, _ = three
    admin_client.post(f"/staff/startups/{a.startup_id}/archive/")
    assert a.startup_id not in ids(admin_client.get("/staff/startups/"))
    assert ids(admin_client.get("/staff/startups/?status=archived")) == {a.startup_id}
    admin_client.post(f"/staff/startups/{a.startup_id}/archive/")  # restore
    assert a.startup_id in ids(admin_client.get("/staff/startups/"))


# -- editing ------------------------------------------------------------------------------

def student_post(student, **changes):
    data = {"first_name": student.first_name, "last_name": student.last_name, "student_number": student.student_number,
            "email": student.email, "phone": student.phone, "domain": student.domain_id, "study_year": student.study_year_id}
    data.update(changes)
    return data


def test_edit_student_is_audited(coach_client, register):
    reg = register()
    student = reg.student
    response = coach_client.post(f"/staff/students/{student.pk}/edit/", student_post(student, phone="+31 6 99999999"))
    assert response.status_code == 302
    student.refresh_from_db()
    assert student.phone == "+31 6 99999999"
    entry = LogEntry.objects.get_for_object(student).filter(action=LogEntry.Action.UPDATE).first()
    assert entry.actor.username == "roeland"
    assert "phone" in entry.changes_dict
    assert "99999999" not in str(entry.changes_dict)  # phone numbers are masked in the audit log


def test_student_number_must_be_unique(coach_client, register):
    a = register(student_number="100001", email="a@buas.nl")
    b = register(student_number="100002", email="b@buas.nl")
    response = coach_client.post(f"/staff/students/{b.student_id}/edit/", student_post(b.student, student_number="100001"))
    assert response.status_code == 200
    assert "merge the two records" in response.content.decode()


def test_employee_needs_no_student_number(coach_client, register):
    reg = register()
    employee = Domain.objects.get(is_employee=True)
    response = coach_client.post(f"/staff/students/{reg.student_id}/edit/", student_post(reg.student, student_number="", domain=employee.pk))
    assert response.status_code == 302


def startup_post(startup, **changes):
    data = {"name": startup.name, "description": startup.description, "goals": startup.goals, "stage": startup.stage_id,
            "assigned_coach": startup.assigned_coach_id or "", "has_paying_customers": "", "idea_validated": "true", "kvk_number": ""}
    data.update(changes)
    return data


def test_edit_startup_with_new_tags_and_kvk(coach_client, register):
    reg = register()
    st = reg.startup
    response = coach_client.post(f"/staff/startups/{st.pk}/edit/", startup_post(st, name="Polder Games", kvk_number="12345678", new_tags="games, Funding needed"))
    assert response.status_code == 302
    st.refresh_from_db()
    assert st.name == "Polder Games" and st.kvk_number == "12345678"
    assert st.has_paying_customers is None and st.idea_validated is True
    assert set(st.tags.values_list("name", flat=True)) == {"games", "Funding needed"}


def test_kvk_number_validation(coach_client, register):
    reg = register()
    response = coach_client.post(f"/staff/startups/{reg.startup_id}/edit/", startup_post(reg.startup, kvk_number="1234"))
    assert "8 digits" in response.content.decode()


def test_assigning_same_domain_coach_to_graduation_founder_needs_confirmation(coach_client, register, graduation_data):
    reg = register(**graduation_data())  # Games student on the graduation track
    hans = Coach.objects.get(first_name="Hans")
    data = startup_post(reg.startup, assigned_coach=hans.pk)
    response = coach_client.post(f"/staff/startups/{reg.startup_id}/edit/", data)
    assert response.status_code == 200
    assert "graduates within their own company" in response.content.decode()
    response = coach_client.post(f"/staff/startups/{reg.startup_id}/edit/", dict(data, confirm_domain="on"))
    assert response.status_code == 302
    reg.startup.refresh_from_db()
    assert reg.startup.assigned_coach == hans


def test_add_idea_for_student(coach_client, register):
    reg = register()
    response = coach_client.post("/staff/startups/new/", {
        "student": reg.student_id, "description": "A second idea", "goals": "", "stage": PipelineStage.initial().pk,
        "assigned_coach": "", "has_paying_customers": "", "idea_validated": "", "kvk_number": "",
    })
    assert response.status_code == 302
    assert reg.student.startups.count() == 2


def test_founders_add_and_remove(coach_client, register):
    a = register(student_number="100001", email="a@buas.nl")
    b = register(student_number="100002", email="b@buas.nl")
    url = f"/staff/startups/{a.startup_id}/"
    assert b.student in coach_client.get(url + "?founder_q=100002").context["founder_results"]
    coach_client.post(url + "founders/add/", {"student": b.student_id, "role": "CTO"})
    assert set(a.startup.founders.all()) == {a.student, b.student}
    link = Founder.objects.get(startup=a.startup, student=b.student)
    assert link.role == "CTO"
    coach_client.post(url + f"founders/{link.pk}/remove/")
    last = Founder.objects.get(startup=a.startup)
    coach_client.post(url + f"founders/{last.pk}/remove/")
    assert Founder.objects.filter(startup=a.startup).count() == 1  # the last founder stays


def test_graduation_approval_closes_reminder(coach_client, register, graduation_data):
    reg = register(**graduation_data(grad_approval="not_yet"))
    track = GraduationTrack.objects.get()
    response = coach_client.post(f"/staff/graduation/{track.pk}/edit/", {
        "approval": "yes", "topic": track.topic, "supervisor_name": track.supervisor_name, "hand_in_date": track.hand_in_date.isoformat(),
    })
    assert response.status_code == 302
    assert FollowUp.objects.get(auto_reason="graduation_approval_missing").done_at is not None


def test_admin_only_notes_hidden_from_coaches(client, make_user, register):
    reg = register()
    Activity.objects.create(startup=reg.startup, kind="note", body="Sensitive: personal circumstances", admin_only=True)
    client.force_login(make_user("coachy", "Coach"))
    assert "Sensitive" not in client.get(f"/staff/startups/{reg.startup_id}/").content.decode()
    client.force_login(make_user("boss", "Admin"))
    assert "Sensitive" in client.get(f"/staff/startups/{reg.startup_id}/").content.decode()


# -- merging ------------------------------------------------------------------------------

@pytest.fixture
def duplicates(register):
    keep = register(student_number="100001", email="sanne@buas.nl", phone="0612345678")
    dup = register(student_number="", email="sanne.private@gmail.com", domain=Domain.objects.get(is_employee=True).pk, phone="0687654321")
    FollowUp.objects.create(student=dup.student, title="Call back", due_date=timezone.localdate())
    return keep, dup


def test_coach_cannot_merge(coach_client, duplicates):
    keep, dup = duplicates
    assert coach_client.post(f"/staff/students/{keep.student_id}/merge/{dup.student_id}/").status_code == 403
    assert coach_client.get(f"/staff/students/{keep.student_id}/merge/").status_code == 403


def test_merge_students(admin_client, duplicates):
    keep, dup = duplicates
    preview = admin_client.get(f"/staff/students/{keep.student_id}/merge/{dup.student_id}/")
    assert preview.status_code == 200 and "sanne.private@gmail.com" in preview.content.decode()

    response = admin_client.post(f"/staff/students/{keep.student_id}/merge/{dup.student_id}/")
    assert response.status_code == 302
    target, merged = Student.objects.get(pk=keep.student_id), Student.objects.get(pk=dup.student_id)
    assert merged.merged_into == target and merged.archived_at
    assert Registration.objects.filter(student=target).count() == 2
    assert target.startups.count() == 2
    assert FollowUp.objects.get(title="Call back").student == target
    assert target.email == "sanne@buas.nl" and target.phone == "0612345678"  # not overwritten
    assert merged not in Student.objects.current()


def test_merge_deduplicates_shared_startup(admin_client, duplicates):
    keep, dup = duplicates
    Founder.objects.create(startup=keep.startup, student=dup.student)
    admin_client.post(f"/staff/students/{keep.student_id}/merge/{dup.student_id}/")
    assert Founder.objects.filter(startup=keep.startup).count() == 1


def test_merge_fills_missing_student_number(admin_client, duplicates):
    keep, dup = duplicates
    admin_client.post(f"/staff/students/{dup.student_id}/merge/{keep.student_id}/")
    assert Student.objects.get(pk=dup.student_id).student_number == "100001"


def test_duplicate_candidates_listed_for_admin(admin_client, register):
    a = register(student_number="100001", email="a@buas.nl")
    b = register(student_number="100002", email="other@buas.nl")  # same name (Sanne de Vries)
    assert b.student in admin_client.get(f"/staff/students/{a.student_id}/").context["candidates"]


# -- walk-ins -----------------------------------------------------------------------------

def walk_in_data(form_data, **overrides):
    data = form_data(**overrides)
    data.pop("website")
    data["send_confirmation"] = "on"
    return data


def test_walk_in(coach_client, form_data, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = coach_client.post("/staff/walk-in/", walk_in_data(form_data))
    reg = Registration.objects.get()
    assert response.url == f"/staff/intake/{reg.pk}/"
    assert reg.source == Registration.Source.WALK_IN
    assert reg.created_by.username == "roeland"
    assert reg.consent_at is not None
    assert [m.to for m in mail.outbox] == [["sanne.devries@buas.nl"]]  # confirmation only, no staff email


def test_walk_in_without_confirmation(coach_client, form_data, django_capture_on_commit_callbacks):
    data = walk_in_data(form_data)
    del data["send_confirmation"]
    with django_capture_on_commit_callbacks(execute=True):
        coach_client.post("/staff/walk-in/", data)
    assert mail.outbox == []


def test_walk_in_requires_consent_and_validates(coach_client, form_data):
    data = walk_in_data(form_data, student_number="12")
    del data["privacy_consent"]
    response = coach_client.post("/staff/walk-in/", data)
    assert response.status_code == 200
    content = response.content.decode()
    assert "confirm that the student agrees" in content and "exactly 6 digits" in content
    assert not Registration.objects.exists()


def test_walk_in_for_known_student(coach_client, register, form_data):
    register()
    response = coach_client.post("/staff/walk-in/", walk_in_data(form_data, description="Another idea"), follow=True)
    assert "already known" in response.content.decode()
    assert Student.objects.count() == 1 and Startup.objects.count() == 2
