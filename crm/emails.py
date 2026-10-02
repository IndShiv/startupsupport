"""Emails and notifications about registrations.

Templates are admin-editable plain text with {{ placeholders }}. Each email is sent
as plain text plus a branded HTML version. Sending never breaks a registration: a
failure is logged on the OutgoingEmail record and can be retried from the admin.
"""

import logging
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe

from siteconfig.models import AppSettings, EmailTemplate, SiteText
from siteconfig.templatetags.sitetext import plaintext_html

from .models import Notification, OutgoingEmail, Registration

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
STAFF_GROUPS = ["Admin", "Coach"]
Key = EmailTemplate.Key


# -- rendering -------------------------------------------------------------------

def answers_text(sections):
    lines = []
    for title, rows in sections:
        lines.append(title.upper())
        for label, value in rows:
            value = str(value)
            label = label if label.endswith(("?", ":")) else f"{label}:"
            if "\n" in value or len(value) > 60:
                lines.append(label)
                lines.extend(f"    {line}" for line in value.splitlines() or [""])
            else:
                lines.append(f"{label} {value}")
        lines.append("")
    return "\n".join(lines).rstrip()


def answers_html(sections):
    return render_to_string("emails/_answers.html", {"sections": sections})


def render_text(template_text, context):
    def replace(match):
        value = context.get(match.group(1))
        return match.group(0) if value is None else str(value)

    text = PLACEHOLDER_RE.sub(replace, template_text)
    # An empty placeholder on its own line must not leave a gap of blank lines.
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text).strip()


def render_html(template_text, context, html_values):
    """Turn the plain-text template into HTML; placeholder values are escaped, except
    `html_values` which are already-safe HTML blocks (such as the answers table)."""
    tokens = {}

    def tokenise(match):
        name = match.group(1)
        if name not in context:
            return match.group(0)
        token = f"⁣{len(tokens)}⁣"
        tokens[token] = name
        return token

    html = str(plaintext_html(PLACEHOLDER_RE.sub(tokenise, template_text)))
    for token, name in tokens.items():
        if name in html_values:
            block = html_values[name]
            html = html.replace(f"<p>{token}</p>", block).replace(token, block)
        else:
            value = str(escape(context[name])).replace("\n", "<br>")
            if not value:
                html = html.replace(f"<p>{token}</p>", "")
            html = html.replace(token, value)
    return html


def render(key, context, html_values, language="en", template=None):
    template = template or EmailTemplate.get(key, language)
    if template is None:
        raise LookupError(f"No email template '{key}'. Run `manage.py seed_reference`.")
    subject = " ".join(render_text(template.subject, context).split())
    text = render_text(template.body, context)
    html_body = render_html(template.body, context, html_values)
    html = render_to_string("emails/base.html", {
        "subject": subject,
        "body": mark_safe(html_body),
        "site_url": settings.SITE_URL,
    })
    return subject, text, html


# -- context ---------------------------------------------------------------------

def _date(value):
    return formats.date_format(value, "l j F Y") if value else "–"


def _contact(registration):
    contact = registration.answers.get("contact") or {}
    student = registration.student
    return {
        "first_name": contact.get("first_name") or student.first_name,
        "last_name": contact.get("last_name") or student.last_name,
        "email": contact.get("email") or student.email,
    }


def _graduation_without_approval(registration):
    track = getattr(registration, "graduation", None)
    return bool(track and track.approval_missing)


def confirmation_context(registration):
    contact = _contact(registration)
    sections = registration.answers.get("sections", [])
    reminder = ""
    if _graduation_without_approval(registration):
        reminder = SiteText.get(
            "graduation_approval_notice",
            "Please arrange approval from your programme as soon as possible and inform your BUSS coach.",
        )
    context = {
        "first_name": contact["first_name"],
        "last_name": contact["last_name"],
        "intake_deadline": _date(registration.intake_deadline),
        "approval_reminder": reminder,
        "answers": answers_text(sections),
        "contact_email": settings.EMAIL_REPLY_TO,
    }
    return context, {"answers": answers_html(sections)}


def staff_flags(registration):
    flags = []
    if registration.is_duplicate_student:
        diffs = registration.answers.get("differences_from_existing_student") or []
        detail = "; ".join(f"{label}: on record “{old}”, now “{new}”" for label, old, new in diffs)
        flags.append("Returning student: linked to an existing record" + (f" ({detail})" if detail else " (details match)."))
    if _graduation_without_approval(registration):
        flags.append("Graduating within own company WITHOUT programme approval yet; a follow-up has been created.")
    elif hasattr(registration, "graduation"):
        flags.append(f"Graduating within own company; hand-in date {_date(registration.graduation.hand_in_date)}.")
    return flags


def record_url(registration):
    return settings.SITE_URL + reverse("admin:crm_registration_change", args=[registration.pk])


def staff_context(registration):
    contact = _contact(registration)
    student = registration.student
    sections = registration.answers.get("sections", [])
    flags = staff_flags(registration)
    subject_flags = []
    if registration.is_duplicate_student:
        subject_flags.append("returning student")
    if _graduation_without_approval(registration):
        subject_flags.append("graduation: approval missing")
    context = {
        "student_name": f"{contact['first_name']} {contact['last_name']}",
        "domain": student.domain.name,
        "study_year": student.study_year.name,
        "submitted_at": formats.date_format(timezone.localtime(registration.submitted_at), "j F Y, H:i"),
        "intake_deadline": _date(registration.intake_deadline),
        "preferred_coach": registration.preferred_coach.full_name if registration.preferred_coach else "No preference",
        "subject_flags": f" [{', '.join(subject_flags)}]" if subject_flags else "",
        "flags": "\n".join(f"- {flag}" for flag in flags) if flags else "- None",
        "record_url": record_url(registration),
        "answers": answers_text(sections),
    }
    html_values = {
        "answers": answers_html(sections),
        "record_url": f'<a href="{escape(context["record_url"])}">{escape(context["record_url"])}</a>',
        "flags": "<ul>" + "".join(f"<li>{escape(f)}</li>" for f in flags) + "</ul>" if flags else "<p>None</p>",
    }
    return context, html_values


# -- sending ---------------------------------------------------------------------

CONTEXT_BUILDERS = {
    Key.REGISTRATION_CONFIRMATION: confirmation_context,
    Key.STAFF_NEW_REGISTRATION: staff_context,
}


def recipient_for(kind, registration):
    if kind == Key.REGISTRATION_CONFIRMATION:
        return _contact(registration)["email"]
    return AppSettings.load().staff_notification_email


def send_registration_email(kind, registration, record=None):
    """Render and send one email; returns the OutgoingEmail log record."""
    to = recipient_for(kind, registration)
    if record is None:
        record = OutgoingEmail(kind=kind, registration=registration, to=to)
    record.attempts += 1
    try:
        context, html_values = CONTEXT_BUILDERS[kind](registration)
        subject, text, html = render(kind, context, html_values)
        record.subject = subject[:255]
        message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [to], reply_to=[settings.EMAIL_REPLY_TO])
        message.attach_alternative(html, "text/html")
        message.send()
    except Exception as exc:  # noqa: BLE001 - any failure is recorded, never raised to the student
        logger.exception("Sending %s for registration %s failed", kind, registration.pk)
        record.status = OutgoingEmail.Status.FAILED
        record.error = f"{type(exc).__name__}: {exc}"[:2000]
        record.subject = record.subject or str(kind)
    else:
        record.status = OutgoingEmail.Status.SENT
        record.error = ""
        record.sent_at = timezone.now()
    record.save()
    return record


def staff_users():
    return User.objects.filter(is_active=True, groups__name__in=STAFF_GROUPS).distinct()


def notify_staff_in_app(registration):
    contact = _contact(registration)
    message = f"New registration: {contact['first_name']} {contact['last_name']} ({registration.student.domain.name})"
    if registration.is_duplicate_student:
        message += " · returning student"
    if _graduation_without_approval(registration):
        message += " · graduation approval missing"
    url = reverse("admin:crm_registration_change", args=[registration.pk])
    Notification.objects.bulk_create(Notification(user=user, message=message[:300], url=url) for user in staff_users())


def registration_submitted(registration_id, *, confirm_to_student=True):
    """Send everything that should happen after a registration is stored."""
    registration = Registration.objects.select_related("student__domain", "student__study_year", "preferred_coach").get(pk=registration_id)
    if confirm_to_student:
        send_registration_email(Key.REGISTRATION_CONFIRMATION, registration)
    mode = AppSettings.load().staff_notification_mode
    if mode in (AppSettings.NotificationMode.EMAIL, AppSettings.NotificationMode.BOTH):
        send_registration_email(Key.STAFF_NEW_REGISTRATION, registration)
    if mode in (AppSettings.NotificationMode.IN_APP, AppSettings.NotificationMode.BOTH):
        notify_staff_in_app(registration)
