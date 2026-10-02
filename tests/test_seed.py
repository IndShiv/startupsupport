import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from crm.models import Coach, GraduationTrack, Registration, Student
from siteconfig.models import Domain, PipelineStage, PrivacyStatement, StudyYear

pytestmark = pytest.mark.django_db


def test_seed_reference_is_idempotent():
    call_command("seed_reference")
    call_command("seed_reference")
    assert Domain.objects.count() == 10
    assert StudyYear.objects.filter(is_graduation_track=True).count() == 1
    assert PipelineStage.initial().name == "Registered"
    assert Coach.objects.count() == 12
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
