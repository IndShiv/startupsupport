import pytest
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from django.core.management import CommandError, call_command

from crm.models import Coach, GraduationTrack, Registration, Student
from siteconfig.models import Domain, PipelineStage, PrivacyStatement, StudyYear

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo_password(monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "test-only-secret")


def test_seed_reference_is_idempotent():
    call_command("seed_reference")
    call_command("seed_reference")
    assert Domain.objects.count() == 10
    assert StudyYear.objects.filter(is_graduation_track=True).count() == 1
    assert PipelineStage.initial().name == "Registered"
    assert Coach.objects.count() == 11
    assert PrivacyStatement.current() is not None
    assert set(Group.objects.values_list("name", flat=True)) == {"Admin", "Coach"}


def test_seed_reference_keeps_admin_edits():
    call_command("seed_reference")
    Domain.objects.filter(name="Games").update(order=999)
    call_command("seed_reference")
    assert Domain.objects.get(name="Games").order == 999


def test_demo_data_covers_every_domain_year_and_graduation_track():
    call_command("seed_demo", force=True)
    for domain in Domain.objects.all():
        assert Student.objects.filter(domain=domain).exists(), domain
    for year in StudyYear.objects.all():
        assert Student.objects.filter(study_year=year).exists(), year
    assert GraduationTrack.objects.filter(approval="not_yet").exists()
    assert GraduationTrack.objects.filter(approval="yes").exists()
    assert Registration.objects.filter(is_duplicate_student=True).exists()
    assert Registration.objects.awaiting_intake().exists()


def test_graduation_track_coaches_are_from_another_domain():
    call_command("seed_demo", force=True)
    for track in GraduationTrack.objects.select_related("startup__assigned_coach", "student__domain"):
        coach = track.startup.assigned_coach
        if coach:
            assert track.student.domain not in coach.domains.all()


def test_demo_data_needs_debug_demo_mode_or_force(settings):
    settings.DEBUG = settings.DEMO_MODE = False
    with pytest.raises(CommandError, match="Refusing"):
        call_command("seed_demo")
    settings.DEMO_MODE = True
    call_command("seed_demo")
    assert Student.objects.exists()


def test_server_needs_its_own_password(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.delenv("DEMO_PASSWORD")
    with pytest.raises(CommandError, match="DEMO_PASSWORD"):
        call_command("seed_demo", force=True)
    assert not User.objects.exists()


def test_demo_logins_use_demo_password(settings):
    settings.LOCAL_LOGIN_ENABLED = True
    call_command("seed_demo", force=True)
    assert authenticate(username="shival", password="test-only-secret")
    assert not authenticate(username="shival", password="buss-dev-2026")
    assert User.objects.get(username="shival").groups.filter(name="Admin").exists()


def test_reset_replaces_demo_data_and_keeps_logins(settings, monkeypatch):
    settings.LOCAL_LOGIN_ENABLED = True
    call_command("seed_demo", force=True)
    Student.objects.filter(pk=Student.objects.first().pk).update(first_name="Changed-by-tester")
    users = User.objects.count()
    monkeypatch.setenv("DEMO_PASSWORD", "new-secret")
    call_command("seed_demo", force=True, reset=True)
    assert not Student.objects.filter(first_name="Changed-by-tester").exists()
    assert Student.objects.count() > 40
    assert User.objects.count() == users
    assert authenticate(username="roeland", password="new-secret")
