"""Send an email template filled with sample data, so editors can check their changes."""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from siteconfig.models import EmailTemplate

from .emails import answers_html, answers_text, render

SAMPLE_SECTIONS = [
    ["About you", [["First name", "Sam"], ["Last name", "Example"], ["Student number", "123456"],
                   ["Email", "sam.example@buas.nl"], ["Domain", "Games"], ["Study year", "Year 2"]]],
    ["Your business", [["Describe your business (idea)", "A sample idea: an app that matches students with local festivals."],
                       ["How can we help you? What are your goals for the coach track?", "Validate the idea and find first customers."]]],
    ["Your coach", [["Preferred coach", "No preference"]]],
]

SAMPLE_CONTEXT = {
    EmailTemplate.Key.REGISTRATION_CONFIRMATION: {
        "first_name": "Sam", "last_name": "Example", "intake_deadline": "Friday 16 October 2026",
        "approval_reminder": "", "contact_email": settings.EMAIL_REPLY_TO,
    },
    EmailTemplate.Key.STAFF_NEW_REGISTRATION: {
        "student_name": "Sam Example", "domain": "Games", "study_year": "Year 2",
        "submitted_at": "2 October 2026, 10:15", "intake_deadline": "Friday 16 October 2026",
        "preferred_coach": "No preference", "subject_flags": " [returning student]",
        "flags": "- Returning student: linked to an existing record (details match).",
        "record_url": settings.SITE_URL + "/admin/",
    },
}


def send_test_email(template, to):
    context = dict(SAMPLE_CONTEXT.get(template.key, {}), answers=answers_text(SAMPLE_SECTIONS))
    html_values = {"answers": answers_html(SAMPLE_SECTIONS)}
    subject, text, html = render(template.key, context, html_values, template=template)
    message = EmailMultiAlternatives(f"[TEST] {subject}", text, settings.DEFAULT_FROM_EMAIL, [to], reply_to=[settings.EMAIL_REPLY_TO])
    message.attach_alternative(html, "text/html")
    message.send()
