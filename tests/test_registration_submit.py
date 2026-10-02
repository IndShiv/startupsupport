"""Submitting the form: stored records, duplicates, spam protection, rate limiting."""

import pytest
from django.urls import reverse

from crm.models import FollowUp, GraduationTrack, Registration, Startup, Student
from crm.workdays import add_working_days
from siteconfig.models import AppSettings, PrivacyStatement

pytestmark = pytest.mark.django_db

URL = "/register/"


def submit(client, data):
    return client.post(URL, data)


def test_form_page_renders(client, reference):
    response = client.get(URL)
    assert response.status_code == 200
    content = response.content.decode()
    assert "Registration takes about 6 minutes" in content
    assert "Shival Indermun" in content
    assert "No preference, I trust you to make the best match" in content
    assert 'name="website"' in content  # honeypot present


def test_root_redirects_to_form(client, reference):
    assert client.get("/").url == reverse("public:register")


def test_submission_creates_records(client, form_data):
    response = submit(client, form_data())
    assert response.status_code == 302
    assert response.url == reverse("public:thanks")

    reg = Registration.objects.get()
    student, startup = reg.student, reg.startup
    assert student.student_number == "234567"
    assert list(startup.founders.all()) == [student]
    assert startup.stage.name == "Registered"
    assert startup.has_paying_customers is False and startup.idea_validated is True
    assert reg.source == Registration.Source.FORM
    assert reg.preferred_coach is None
    assert reg.consent_at is not None
    assert reg.privacy_statement == PrivacyStatement.current()
    assert reg.intake_deadline == add_working_days(reg.submitted_at.date(), 10)
    assert not reg.is_duplicate_student
    assert reg.answers["sections"][0][0] == "About you"
    assert not GraduationTrack.objects.exists()

    thanks = client.get(response.url)
    assert "10 working days" in thanks.content.decode()


def test_invalid_submission_keeps_answers(client, form_data):
    response = submit(client, form_data(student_number="12", description="A bakery that delivers by bike."))
    assert response.status_code == 400
    content = response.content.decode()
    assert "exactly 6 digits" in content
    assert "A bakery that delivers by bike." in content
    assert 'value="Sanne"' in content
    assert not Registration.objects.exists()


def test_graduation_track_without_approval_creates_follow_up(client, graduation_data):
    submit(client, graduation_data(grad_approval="not_yet"))
    track = GraduationTrack.objects.get()
    assert track.approval_missing
    follow_up = FollowUp.objects.get()
    assert follow_up.auto_reason == "graduation_approval_missing"
    assert follow_up.student == track.student


def test_graduation_track_with_approval_has_no_follow_up(client, graduation_data):
    submit(client, graduation_data(grad_approval="yes"))
    assert GraduationTrack.objects.get().approval == "yes"
    assert not FollowUp.objects.exists()


# -- duplicates ---------------------------------------------------------------

def test_same_student_number_links_to_existing_student(client, form_data):
    submit(client, form_data())
    response = submit(client, form_data(email="other@gmail.com", phone="0612345678", description="A second, different idea."))
    assert response.status_code == 302

    assert Student.objects.count() == 1
    assert Startup.objects.count() == 2
    student = Student.objects.get()
    assert student.startups.count() == 2
    second = Registration.objects.order_by("submitted_at").last()
    assert second.is_duplicate_student
    # Existing details are not overwritten; differences are recorded for staff.
    assert student.email == "sanne.devries@buas.nl"
    diffs = {row[0] for row in second.answers["differences_from_existing_student"]}
    assert diffs == {"Email", "Phone"}


def test_same_email_links_to_existing_student(client, form_data):
    submit(client, form_data())
    submit(client, form_data(student_number="345678", email="SANNE.DEVRIES@buas.nl"))
    assert Student.objects.count() == 1
    assert Registration.objects.filter(is_duplicate_student=True).count() == 1


def test_duplicate_follows_merged_student(client, form_data):
    submit(client, form_data())
    original = Student.objects.get()
    survivor = Student.objects.create(first_name="Sanne", last_name="de Vries", student_number="999999",
                                      email="s.devries@buas.nl", phone="0612345678",
                                      domain=original.domain, study_year=original.study_year)
    original.merged_into = survivor
    original.save()
    submit(client, form_data())
    assert Registration.objects.order_by("submitted_at").last().student == survivor


def test_anonymised_student_is_not_matched(client, form_data):
    submit(client, form_data())
    Student.objects.update(anonymised_at="2026-01-01T00:00:00Z")
    submit(client, form_data())
    assert Student.objects.count() == 2
    assert not Registration.objects.filter(is_duplicate_student=True).exists()


def test_different_student_is_new(client, form_data):
    submit(client, form_data())
    submit(client, form_data(student_number="345678", email="someone.else@buas.nl"))
    assert Student.objects.count() == 2


# -- spam protection ----------------------------------------------------------

def test_honeypot_stores_nothing_but_looks_successful(client, form_data):
    response = submit(client, form_data(website="http://spam.example"))
    assert response.status_code == 302
    assert response.url == reverse("public:thanks")
    assert not Registration.objects.exists()


def test_rate_limit(client, form_data):
    AppSettings.objects.filter(pk=1).update(rate_limit_per_hour=2)
    assert submit(client, form_data(student_number="100001", email="a@buas.nl")).status_code == 302
    assert submit(client, form_data(student_number="100002", email="b@buas.nl")).status_code == 302
    response = submit(client, form_data(student_number="100003", email="c@buas.nl"))
    assert response.status_code == 429
    assert Registration.objects.count() == 2


def test_rate_limit_is_per_ip(client, form_data):
    AppSettings.objects.filter(pk=1).update(rate_limit_per_hour=1)
    assert submit(client, form_data()).status_code == 302
    assert client.post(URL, form_data(student_number="100002", email="b@buas.nl"), REMOTE_ADDR="10.0.0.2").status_code == 302
    assert submit(client, form_data(student_number="100003", email="c@buas.nl")).status_code == 429


def test_privacy_page(client, reference):
    response = client.get(reverse("public:privacy"))
    assert response.status_code == 200
    assert "What we store" in response.content.decode()


def test_public_pages_show_branding_and_partners(client, reference):
    for url in (URL, reverse("public:thanks"), reverse("public:privacy")):
        content = client.get(url).content.decode()
        assert 'alt="Breda University of Applied Sciences"' in content
        assert 'alt="B&#x27;WISE"' in content
        assert "startupsupport@buas.nl" in content


def test_inactive_partner_is_hidden(client, reference):
    from siteconfig.models import Partner

    Partner.objects.update(active=False)
    content = client.get(URL).content.decode()
    assert "Supported by" not in content
