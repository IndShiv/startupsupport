"""Validation of the public registration form, including the conditional graduation section."""

from datetime import timedelta

import pytest
from django.utils import timezone

from crm.models import Coach
from public.forms import RegistrationForm
from siteconfig.models import Domain

pytestmark = pytest.mark.django_db


def errors_for(data):
    form = RegistrationForm(data)
    form.is_valid()
    return form.errors


def test_valid_form(form_data):
    form = RegistrationForm(form_data())
    assert form.is_valid(), form.errors
    assert form.cleaned_data["preferred_coach"] is None  # "No preference"


@pytest.mark.parametrize("field", ["first_name", "last_name", "email", "phone", "domain", "study_year", "description", "goals", "preferred_coach", "privacy_consent"])
def test_required_fields(form_data, field):
    assert field in errors_for(form_data(**{field: None}))


def test_optional_fields(form_data):
    assert not errors_for(form_data(has_paying_customers=None, idea_validated=None, comments=None))


@pytest.mark.parametrize("number", ["12345", "1234567", "abcdef", "12 34 5"])
def test_invalid_student_number(form_data, number):
    assert "student_number" in errors_for(form_data(student_number=number))


def test_student_number_spaces_are_stripped(form_data):
    form = RegistrationForm(form_data(student_number=" 234 567 "))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["student_number"] == "234567"


def test_student_number_required_for_students(form_data):
    assert "student_number" in errors_for(form_data(student_number=""))


def test_student_number_optional_for_employees(form_data):
    employee = Domain.objects.get(is_employee=True)
    assert not errors_for(form_data(student_number="", domain=employee.pk))
    # ...but if an employee fills it in, it must still be valid.
    assert "student_number" in errors_for(form_data(student_number="12", domain=employee.pk))


@pytest.mark.parametrize("email", ["not-an-email", "name@", "@buas.nl"])
def test_invalid_email(form_data, email):
    assert "email" in errors_for(form_data(email=email))


def test_non_buas_email_is_accepted_and_lowercased(form_data):
    form = RegistrationForm(form_data(email="Sanne@Gmail.com"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["email"] == "sanne@gmail.com"


@pytest.mark.parametrize("phone", ["12345", "call me", "+31 6 1234 5678 9012 34"])
def test_invalid_phone(form_data, phone):
    assert "phone" in errors_for(form_data(phone=phone))


@pytest.mark.parametrize("phone", ["0612345678", "+31 6 12345678", "+32 470 12 34 56"])
def test_valid_phone(form_data, phone):
    assert not errors_for(form_data(phone=phone))


def test_description_word_limit(form_data):
    assert not errors_for(form_data(description=" ".join(["word"] * 200)))
    errors = errors_for(form_data(description=" ".join(["word"] * 201)))
    assert "description" in errors
    assert "201" in errors["description"][0]


def test_inactive_coach_cannot_be_chosen(form_data, coach):
    Coach.objects.filter(pk=coach.pk).update(active=False)
    assert "preferred_coach" in errors_for(form_data(preferred_coach=str(coach.pk)))


def test_active_coach_can_be_chosen(form_data, coach):
    form = RegistrationForm(form_data(preferred_coach=str(coach.pk)))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["preferred_coach"] == coach


def test_privacy_version_must_be_published(form_data):
    assert "privacy_version" in errors_for(form_data(privacy_version=9999))


# -- graduation section ------------------------------------------------------

def test_graduation_section_valid(graduation_data):
    form = RegistrationForm(graduation_data())
    assert form.is_valid(), form.errors
    assert form.on_graduation_track


@pytest.mark.parametrize("field", ["grad_approval", "grad_topic", "grad_supervisor", "grad_hand_in_date"])
def test_graduation_fields_required_on_graduation_track(graduation_data, field):
    assert field in errors_for(graduation_data(**{field: None}))


def test_graduation_fields_ignored_when_not_on_graduation_track(form_data):
    # Junk in the hidden section must neither block nor be saved for other study years.
    form = RegistrationForm(form_data(grad_approval="bogus", grad_topic=" ".join(["w"] * 300), grad_hand_in_date="2001-01-01"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["grad_topic"] is None
    assert form.cleaned_data["grad_hand_in_date"] is None


def test_graduation_topic_word_limit(graduation_data):
    assert not errors_for(graduation_data(grad_topic=" ".join(["word"] * 100)))
    assert "grad_topic" in errors_for(graduation_data(grad_topic=" ".join(["word"] * 101)))


@pytest.mark.parametrize("days", [0, -1, -30])
def test_hand_in_date_must_be_in_future(graduation_data, days):
    date = (timezone.localdate() + timedelta(days=days)).isoformat()
    assert "grad_hand_in_date" in errors_for(graduation_data(grad_hand_in_date=date))


def test_hand_in_date_must_be_a_date(graduation_data):
    assert "grad_hand_in_date" in errors_for(graduation_data(grad_hand_in_date="next spring"))


def test_summary_contains_graduation_section_only_on_track(form_data, graduation_data):
    form = RegistrationForm(form_data())
    assert form.is_valid()
    assert "Graduating within your own company" not in [title for title, _ in form.summary()]
    form = RegistrationForm(graduation_data(grad_approval="not_yet"))
    assert form.is_valid()
    sections = dict(form.summary())
    assert ("Do you have approval from your programme to graduate with your own company?", "No, not yet") in sections["Graduating within your own company"]
