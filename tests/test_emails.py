"""Confirmation and staff emails, in-app notifications and the Graph sender."""

import json
from unittest import mock

import pytest
from django.core import mail
from django.test import override_settings

from crm import emails
from crm.models import Notification, OutgoingEmail, Registration
from siteconfig.models import AppSettings, EmailTemplate

pytestmark = pytest.mark.django_db

URL = "/register/"


@pytest.fixture
def staff(reference, django_user_model):
    from django.contrib.auth.models import Group

    users = []
    for name, group in [("coach1", "Coach"), ("admin1", "Admin")]:
        user = django_user_model.objects.create_user(name, f"{name}@example.org", "x", is_staff=True)
        user.groups.add(Group.objects.get(name=group))
        users.append(user)
    django_user_model.objects.create_user("outsider", "o@example.org", "x")  # not staff: no notification
    return users


def submit(client, data, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(URL, data)
    assert response.status_code == 302, response.content.decode()[:500]
    return Registration.objects.order_by("-pk").first()


def by_recipient(address):
    return [m for m in mail.outbox if address in m.to]


def test_confirmation_email_to_student(client, form_data, staff, django_capture_on_commit_callbacks):
    reg = submit(client, form_data(email="Sanne@Gmail.com"), django_capture_on_commit_callbacks)
    [message] = by_recipient("sanne@gmail.com")
    assert message.subject == "We have received your registration – BUas Startup Support"
    assert message.reply_to == ["startupsupport@buas.nl"]
    assert "Dear Sanne," in message.body
    assert "An indie studio developing a cosy farming game" in message.body  # summary of answers
    assert "Graduating within your own company" not in message.body
    html = message.alternatives[0][0]
    assert "<table" in html and "Dear Sanne," in html
    assert "\n\n\n" not in message.body  # empty approval reminder leaves no gap
    log = OutgoingEmail.objects.get(kind=EmailTemplate.Key.REGISTRATION_CONFIRMATION)
    assert log.status == OutgoingEmail.Status.SENT and log.registration == reg and log.to == "sanne@gmail.com"


def test_confirmation_includes_approval_reminder(client, graduation_data, staff, django_capture_on_commit_callbacks):
    submit(client, graduation_data(grad_approval="not_yet"), django_capture_on_commit_callbacks)
    [message] = by_recipient("sanne.devries@buas.nl")
    assert "Please arrange approval from your programme" in message.body
    assert "Graduation assignment topic" in message.body


def test_staff_email(client, form_data, staff, django_capture_on_commit_callbacks):
    reg = submit(client, form_data(), django_capture_on_commit_callbacks)
    [message] = by_recipient("startupsupport@buas.nl")
    assert message.subject == "New BUSS registration: Sanne de Vries (Games)"
    assert f"/staff/intake/{reg.pk}/" in message.body
    assert "- None" in message.body


def test_staff_email_flags_returning_student(client, form_data, staff, django_capture_on_commit_callbacks):
    submit(client, form_data(), django_capture_on_commit_callbacks)
    mail.outbox.clear()
    submit(client, form_data(phone="0612345678", description="Second idea"), django_capture_on_commit_callbacks)
    [message] = by_recipient("startupsupport@buas.nl")
    assert "[returning student]" in message.subject
    assert "Returning student: linked to an existing record" in message.body
    assert "Phone: on record" in message.body


def test_staff_email_flags_missing_approval(client, graduation_data, staff, django_capture_on_commit_callbacks):
    submit(client, graduation_data(grad_approval="not_yet"), django_capture_on_commit_callbacks)
    [message] = by_recipient("startupsupport@buas.nl")
    assert "graduation: approval missing" in message.subject
    assert "WITHOUT programme approval" in message.body


@pytest.mark.parametrize("mode, expect_email, expect_in_app", [
    ("email", True, False),
    ("in_app", False, True),
    ("both", True, True),
])
def test_notification_mode(client, form_data, staff, django_capture_on_commit_callbacks, mode, expect_email, expect_in_app):
    AppSettings.objects.filter(pk=1).update(staff_notification_mode=mode)
    submit(client, form_data(), django_capture_on_commit_callbacks)
    assert bool(by_recipient("startupsupport@buas.nl")) == expect_email
    assert Notification.objects.exists() == expect_in_app
    if expect_in_app:
        assert set(Notification.objects.values_list("user__username", flat=True)) == {"admin1"}
    assert len(by_recipient("sanne.devries@buas.nl")) == 1  # student always gets a confirmation


def test_staff_address_is_configurable(client, form_data, staff, django_capture_on_commit_callbacks):
    AppSettings.objects.filter(pk=1).update(staff_notification_email="team@example.org")
    submit(client, form_data(), django_capture_on_commit_callbacks)
    assert by_recipient("team@example.org")


def test_edited_template_is_used(client, form_data, staff, django_capture_on_commit_callbacks):
    EmailTemplate.objects.filter(key="registration_confirmation").update(
        subject="Hi {{ first_name }}!", body="Deadline {{ intake_deadline }}. {{ unknown_placeholder }}")
    submit(client, form_data(), django_capture_on_commit_callbacks)
    [message] = by_recipient("sanne.devries@buas.nl")
    assert message.subject == "Hi Sanne!"
    assert message.body.startswith("Deadline ")
    assert "{{ unknown_placeholder }}" in message.body  # left visible so editors notice typos


def test_dutch_template_falls_back_to_english(reference):
    assert EmailTemplate.get("registration_confirmation", "nl").language == "en"


def test_values_are_escaped_in_html(client, form_data, staff, django_capture_on_commit_callbacks):
    submit(client, form_data(first_name="<b>Sanne</b>"), django_capture_on_commit_callbacks)
    [message] = by_recipient("sanne.devries@buas.nl")
    html = message.alternatives[0][0]
    assert "<b>Sanne</b>" not in html
    assert "&lt;b&gt;Sanne&lt;/b&gt;" in html


def test_failed_email_does_not_break_registration_and_can_be_retried(client, form_data, staff, django_capture_on_commit_callbacks):
    with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("SMTP down")):
        reg = submit(client, form_data(), django_capture_on_commit_callbacks)
    assert Registration.objects.count() == 1
    failed = OutgoingEmail.objects.filter(status=OutgoingEmail.Status.FAILED)
    assert failed.count() == 2
    assert "SMTP down" in failed.first().error

    record = failed.get(kind="registration_confirmation")
    emails.send_registration_email(record.kind, reg, record=record)
    record.refresh_from_db()
    assert record.status == OutgoingEmail.Status.SENT and record.attempts == 2


def test_honeypot_sends_nothing(client, form_data, staff, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        client.post(URL, form_data(website="spam"))
    assert mail.outbox == []


def test_email_log_does_not_store_body(reference):
    field_names = {f.name for f in OutgoingEmail._meta.fields}
    assert not field_names & {"body", "html", "text"}


def test_send_test_email(reference):
    from crm.email_preview import send_test_email

    for template in EmailTemplate.objects.all():
        send_test_email(template, "editor@example.org")
    assert len(mail.outbox) == 2
    assert all(m.subject.startswith("[TEST]") for m in mail.outbox)


# -- Microsoft Graph backend ----------------------------------------------------------

class FakeResponse:
    def __init__(self, status, body=b""):
        self.status, self._body = status, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@override_settings(
    EMAIL_BACKEND="buss.mail_graph.GraphEmailBackend",
    GRAPH_TENANT_ID="tenant", GRAPH_CLIENT_ID="client", GRAPH_CLIENT_SECRET="secret",
    GRAPH_SENDER="startupsupport@buas.nl",
)
def test_graph_backend_sends_html_via_graph():
    from django.core.mail import EmailMultiAlternatives

    from buss import mail_graph

    mail_graph._token_cache.update(value=None, expires=0)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        if "oauth2" in request.full_url:
            return FakeResponse(200, json.dumps({"access_token": "tok", "expires_in": 3600}).encode())
        return FakeResponse(202)

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        message = EmailMultiAlternatives("Hello", "plain", "BUSS <startupsupport@buas.nl>", ["Sam <sam@example.org>"], reply_to=["startupsupport@buas.nl"])
        message.attach_alternative("<p>html</p>", "text/html")
        assert message.send() == 1

    token_call, send_call = calls
    assert "login.microsoftonline.com/tenant/" in token_call.full_url
    assert send_call.full_url == "https://graph.microsoft.com/v1.0/users/startupsupport%40buas.nl/sendMail"
    assert send_call.headers["Authorization"] == "Bearer tok"
    payload = json.loads(send_call.data)
    assert payload["message"]["body"] == {"contentType": "HTML", "content": "<p>html</p>"}
    assert payload["message"]["toRecipients"] == [{"emailAddress": {"address": "sam@example.org", "name": "Sam"}}]
    assert payload["message"]["replyTo"][0]["emailAddress"]["address"] == "startupsupport@buas.nl"
