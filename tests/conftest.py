from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone

from crm.models import Coach
from siteconfig.models import Domain, PrivacyStatement, StudyYear


@pytest.fixture
def reference(db):
    call_command("seed_reference", verbosity=0)
    cache.clear()


@pytest.fixture
def form_data(reference):
    """Build valid POST data for the registration form; override fields with keyword arguments."""

    def build(**overrides):
        data = {
            "first_name": "Sanne",
            "last_name": "de Vries",
            "student_number": "234567",
            "email": "sanne.devries@buas.nl",
            "phone": "+31 6 00123456",
            "domain": Domain.objects.get(name="Games").pk,
            "study_year": StudyYear.objects.get(name="Year 2").pk,
            "description": "An indie studio developing a cosy farming game about Dutch polder life.",
            "has_paying_customers": "no",
            "idea_validated": "yes",
            "goals": "Find funding and plan a Kickstarter campaign.",
            "preferred_coach": "none",
            "comments": "",
            "privacy_consent": "on",
            "privacy_version": PrivacyStatement.current().pk,
            "website": "",
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not None}

    return build


@pytest.fixture
def graduation_data(form_data):
    def build(**overrides):
        values = {
            "study_year": StudyYear.objects.get(is_graduation_track=True).pk,
            "grad_approval": "yes",
            "grad_topic": "Go-to-market strategy for the German market.",
            "grad_supervisor": "Dr. A. Jansen",
            "grad_hand_in_date": (timezone.localdate() + timedelta(days=60)).isoformat(),
        }
        values.update(overrides)
        return form_data(**values)

    return build


@pytest.fixture
def coach(reference):
    return Coach.objects.get(first_name="Shival")


@pytest.fixture
def make_user(reference, django_user_model):
    from django.contrib.auth.models import Group

    def build(username, group=None, coach=None):
        user = django_user_model.objects.create_user(username, f"{username}@example.org", "pw")
        if group:
            user.groups.add(Group.objects.get(name=group))
        if coach:
            coach.user = user
            coach.save()
        return user

    return build


@pytest.fixture
def register(client, form_data):
    """Submit the public form and return the new Registration."""
    from crm.models import Registration

    def build(**overrides):
        response = client.post("/register/", form_data(**overrides))
        assert response.status_code == 302, response.content.decode()[:300]
        return Registration.objects.order_by("-pk").first()

    return build
