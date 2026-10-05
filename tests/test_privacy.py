"""GDPR tools: export, anonymise, delete, retention."""

import json
from datetime import timedelta

import pytest
from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.utils import timezone

from crm import privacy
from crm.models import (
    Activity, Founder, FollowUp, GraduationTrack, ImportBatch, Notification, OutgoingEmail, PrivacyAction, Registration,
    Startup, Student,
)
from siteconfig.models import PipelineStage, StudyYear

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(make_user):
    return make_user("boss", "Admin")


@pytest.fixture
def admin_client(client, admin):
    client.force_login(admin)
    return client


@pytest.fixture
def register(register, django_capture_on_commit_callbacks):
    """Like the shared fixture, but also runs the on-commit email sending so the email log is filled."""

    def build(**overrides):
        with django_capture_on_commit_callbacks(execute=True):
            return register(**overrides)

    return build


@pytest.fixture
def reg(register, admin):
    """A registered student with an activity and a follow-up on their startup."""
    registration = register(comments="Please call me after 4 pm.")
    Activity.objects.create(startup=registration.startup, author=admin, body="Discussed pricing with Sanne.")
    FollowUp.objects.create(startup=registration.startup, student=registration.student, title="Call Sanne",
                            notes="Mobile 06 00123456", due_date=timezone.localdate(), assigned_to=admin)
    return registration


def log_entries(obj):
    return LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(obj), object_pk=str(obj.pk))


# -- access ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "/staff/privacy/", "/staff/students/{pk}/privacy/export.json",
    "/staff/students/{pk}/privacy/anonymise/", "/staff/students/{pk}/privacy/delete/",
])
def test_admin_only(client, make_user, coach, reg, url):
    url = url.format(pk=reg.student.pk)
    assert client.get(url).status_code == 302  # to login
    client.force_login(make_user("shival", "Coach", coach=coach))
    assert client.get(url).status_code == 403
    assert client.post("/staff/privacy/anonymise/", {"student": reg.student.pk}).status_code == 403
    assert Student.objects.get(pk=reg.student.pk).anonymised_at is None


def test_student_page_shows_privacy_section_to_admins_only(client, make_user, coach, reg):
    url = f"/staff/students/{reg.student.pk}/"
    client.force_login(make_user("shival", "Coach", coach=coach))
    assert "privacy/export.json" not in client.get(url).content.decode()
    client.force_login(make_user("boss2", "Admin"))
    assert "privacy/export.json" in client.get(url).content.decode()


# -- export ---------------------------------------------------------------------------------------

def test_export_contains_everything_about_the_student(admin_client, reg, admin):
    response = admin_client.get(f"/staff/students/{reg.student.pk}/privacy/export.json")
    assert response["Content-Type"].startswith("application/json")
    assert "attachment" in response["Content-Disposition"]
    assert response["Cache-Control"] == "no-store"
    data = json.loads(response.content)
    assert data["student"]["first_name"] == "Sanne"
    assert data["student"]["student_number"] == "234567"
    assert data["student"]["email"] == "sanne.devries@buas.nl"
    [r] = data["registrations"]
    assert r["comments"] == "Please call me after 4 pm."
    assert r["privacy_consent_at"] and r["privacy_statement_version"]
    assert r["answers"]
    [startup] = data["startups"]
    assert startup["description"].startswith("An indie studio")
    assert any(a["text"] == "Discussed pricing with Sanne." for a in startup["activity_log"])
    assert data["follow_ups"][0]["title"] == "Call Sanne"
    assert "sanne.devries@buas.nl" in [e["to"] for e in data["emails_sent"]]
    assert data["change_history"]
    action = PrivacyAction.objects.get()
    assert (action.action, action.student_ref, action.performed_by) == ("export", reg.student.pk, admin)


def test_export_leaves_out_co_founders(admin_client, reg, register):
    other = register(first_name="Tom", last_name="Bakker", student_number="345678", email="tom.bakker@buas.nl")
    Founder.objects.create(startup=reg.startup, student=other.student)
    text = admin_client.get(f"/staff/students/{reg.student.pk}/privacy/export.json").content.decode()
    data = json.loads(text)
    shared = next(s for s in data["startups"] if s["id"] == reg.startup.pk)
    assert shared["other_founders"] == 1
    assert "Bakker" not in text and "345678" not in text and "tom.bakker" not in text


def test_export_includes_merged_duplicates(reg, register):
    dup = register(email="sanne.private@example.org", student_number="999999", first_name="S.", last_name="Vries")
    if dup.student_id == reg.student_id:  # matched as the same student; force a separate record
        pytest.skip("duplicate detection linked the registration")
    Student.objects.filter(pk=dup.student_id).update(merged_into=reg.student)
    data = privacy.export_student(reg.student)
    assert [s["email"] for s in data["merged_duplicate_records"]] == ["sanne.private@example.org"]
    assert len(data["registrations"]) == 2


# -- anonymise ------------------------------------------------------------------------------------

def test_anonymise_requires_reason_and_confirmation(admin_client, reg):
    url = f"/staff/students/{reg.student.pk}/privacy/anonymise/"
    assert "Please tick" in admin_client.post(url, {"reason": "Student asked"}).content.decode()
    assert "Please give a reason" in admin_client.post(url, {"confirm": "on", "reason": " "}).content.decode()
    assert Student.objects.get(pk=reg.student.pk).anonymised_at is None
    assert not PrivacyAction.objects.exists()


def test_anonymise_removes_personal_data_and_keeps_statistics(admin_client, reg, admin):
    student, startup = reg.student, reg.startup
    assert log_entries(student).exists()
    Notification.objects.create(user=admin, message="New registration: Sanne de Vries", url=f"/staff/intake/{reg.pk}/")
    response = admin_client.post(f"/staff/students/{student.pk}/privacy/anonymise/",
                                 {"confirm": "on", "reason": "Request by email"})
    assert response.status_code == 302

    student.refresh_from_db()
    assert (student.first_name, student.last_name) == ("Anonymised", f"student #{student.pk}")
    assert student.student_number == student.email == student.phone == ""
    assert student.anonymised_at and student.archived_at
    assert student.domain.name == "Games" and student.study_year.name == "Year 2"  # statistics stay

    reg.refresh_from_db()
    assert reg.answers == {} and reg.comments == ""
    assert reg.submitted_at and reg.intake_deadline and reg.consent_at  # dates stay

    startup.refresh_from_db()
    assert startup.name == "" and startup.description == privacy.ANONYMISED and startup.goals == ""
    assert startup.archived_at and startup.stage  # stage kept for the pipeline statistics
    assert set(Activity.objects.filter(startup=startup).values_list("body", flat=True)) == {privacy.ANONYMISED}
    assert not FollowUp.objects.filter(student=student).exists()
    assert set(OutgoingEmail.objects.filter(registration=reg).values_list("to", flat=True)) == {""}

    # The audit log holds old values, so it goes too; and so does the "new registration" notification.
    assert not log_entries(student).exists() and not log_entries(reg).exists()
    assert not Notification.objects.filter(url=f"/staff/intake/{reg.pk}/").exists()

    action = PrivacyAction.objects.get(action="anonymise")
    assert action.student_ref == student.pk and action.reason == "Request by email" and action.performed_by == admin
    assert "Sanne" not in json.dumps(action.details)


def test_anonymised_student_is_hidden_from_lists_and_pages(admin_client, reg):
    privacy.anonymise_student(reg.student)
    assert "Anonymised" not in admin_client.get("/staff/students/").content.decode()
    assert admin_client.get(f"/staff/students/{reg.student.pk}/edit/").status_code == 404
    assert admin_client.get(f"/staff/students/{reg.student.pk}/privacy/anonymise/").status_code == 404


def test_anonymise_graduation_track(graduation_data, client):
    client.post("/register/", graduation_data())
    track = GraduationTrack.objects.get()
    privacy.anonymise_student(track.student)
    track.refresh_from_db()
    assert track.topic == track.supervisor_name == privacy.ANONYMISED
    assert track.hand_in_date and track.approval == "yes"


def test_anonymise_shared_startup_only_removes_the_founder(reg, register):
    other = register(first_name="Tom", last_name="Bakker", student_number="345678", email="tom.bakker@buas.nl")
    Founder.objects.create(startup=reg.startup, student=other.student)
    details = privacy.anonymise_student(reg.student)
    assert details["removed_from_shared_startups"] == 1
    startup = Startup.objects.get(pk=reg.startup.pk)
    assert startup.description.startswith("An indie studio") and startup.archived_at is None
    assert list(startup.founders.all()) == [other.student]
    assert Activity.objects.filter(startup=startup, body="Discussed pricing with Sanne.").exists()


def test_anonymise_also_covers_merged_duplicates(reg, register):
    dup = register(email="sanne.private@example.org", student_number="999999", first_name="S.", last_name="Vries")
    if dup.student_id == reg.student_id:
        pytest.skip("duplicate detection linked the registration")
    Student.objects.filter(pk=dup.student_id).update(merged_into=reg.student)
    privacy.anonymise_student(reg.student)
    merged = Student.objects.get(pk=dup.student_id)
    assert merged.email == "" and merged.first_name == "Anonymised" and merged.anonymised_at


# -- delete ---------------------------------------------------------------------------------------

def test_delete_removes_student_and_their_records(admin_client, reg, admin):
    student_pk, startup_pk, reg_pk = reg.student.pk, reg.startup.pk, reg.pk
    response = admin_client.post(f"/staff/students/{student_pk}/privacy/delete/",
                                 {"confirm": "on", "reason": "Asked to be forgotten"})
    assert response.status_code == 302 and response["Location"] == "/staff/privacy/"
    assert not Student.objects.filter(pk=student_pk).exists()
    assert not Registration.objects.filter(pk=reg_pk).exists()
    assert not Startup.objects.filter(pk=startup_pk).exists()
    assert not Activity.objects.filter(startup_id=startup_pk).exists()
    assert not FollowUp.objects.exists()
    assert not OutgoingEmail.objects.exists()
    assert not LogEntry.objects.filter(object_pk=str(student_pk),
                                       content_type=ContentType.objects.get_for_model(Student)).exists()
    action = PrivacyAction.objects.get(action="delete")
    assert action.student_ref == student_pk and action.performed_by == admin


def test_delete_keeps_shared_startup(reg, register):
    other = register(first_name="Tom", last_name="Bakker", student_number="345678", email="tom.bakker@buas.nl")
    Founder.objects.create(startup=reg.startup, student=other.student)
    privacy.delete_student(other.student)
    assert Startup.objects.filter(pk=reg.startup.pk).exists()
    assert list(Startup.objects.get(pk=reg.startup.pk).founders.all()) == [reg.student]


# -- retention ------------------------------------------------------------------------------------

def age(registration, days):
    """Make a registration and everything around it look `days` old."""
    then = timezone.now() - timedelta(days=days)
    Registration.objects.filter(pk=registration.pk).update(submitted_at=then)
    Student.objects.filter(pk=registration.student_id).update(updated_at=then)
    Startup.objects.filter(pk=registration.startup_id).update(updated_at=then, last_activity_at=then)


def test_due_for_anonymisation(register):
    old = register()
    recent = register(first_name="Tom", last_name="Bakker", student_number="345678", email="tom.bakker@buas.nl")
    age(old, 3 * 365)
    age(recent, 300)
    assert [s.pk for s in privacy.due_for_anonymisation()] == [old.student_id]
    # Recent activity on the startup keeps the record.
    Startup.objects.filter(pk=old.startup_id).update(last_activity_at=timezone.now())
    assert privacy.due_for_anonymisation() == []


def test_retention_period_is_configurable(register):
    from siteconfig.models import AppSettings

    r = register()
    age(r, 400)
    assert privacy.due_for_anonymisation() == []
    settings = AppSettings.load()
    settings.retention_years = 1
    settings.save()
    assert [s.pk for s in privacy.due_for_anonymisation()] == [r.student_id]


def test_privacy_page_and_bulk_anonymise_only_due_students(admin_client, register):
    old = register()
    recent = register(first_name="Tom", last_name="Bakker", student_number="345678", email="tom.bakker@buas.nl")
    age(old, 3 * 365)
    page = admin_client.get("/staff/privacy/").content.decode()
    assert "de Vries" in page and "Bakker" not in page
    response = admin_client.post("/staff/privacy/anonymise/", {"student": [old.student_id, recent.student_id]})
    assert response.status_code == 302
    assert Student.objects.get(pk=old.student_id).anonymised_at
    assert Student.objects.get(pk=recent.student_id).anonymised_at is None
    assert PrivacyAction.objects.get().reason == "Retention period passed"


def test_retention_check_notifies_admins_and_cleans_up(register, admin, make_user, coach):
    coach_user = make_user("shival", "Coach", coach=coach)
    r = register()
    age(r, 3 * 365)
    old_note = Notification.objects.create(user=admin, message="old", url="/x/")
    Notification.objects.filter(pk=old_note.pk).update(created_at=timezone.now() - timedelta(days=400))
    assert OutgoingEmail.objects.filter(registration=r).exists()
    OutgoingEmail.objects.filter(registration=r).update(created_at=timezone.now() - timedelta(days=3 * 365))
    batch = ImportBatch.objects.create(filename="x.xlsx")
    ImportBatch.objects.filter(pk=batch.pk).update(created_at=timezone.now() - timedelta(days=2))

    call_command("retention_check", verbosity=0)
    call_command("retention_check", verbosity=0)  # running twice leaves one reminder

    reminders = Notification.objects.filter(url="/staff/privacy/")
    assert [n.user for n in reminders] == [admin]
    assert "1 student record" in reminders[0].message
    assert not Notification.objects.filter(user=coach_user, url="/staff/privacy/").exists()
    assert not Notification.objects.filter(pk=old_note.pk).exists()
    assert not OutgoingEmail.objects.filter(registration=r).exists()
    assert not ImportBatch.objects.exists()
    # It never anonymises by itself.
    assert Student.objects.get(pk=r.student_id).anonymised_at is None


def test_retention_check_quiet_when_nothing_is_due(register, admin):
    register()
    call_command("retention_check", verbosity=0)
    assert not Notification.objects.filter(url="/staff/privacy/").exists()
