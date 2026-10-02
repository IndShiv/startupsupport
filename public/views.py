from functools import partial

from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from crm import emails
from crm.models import Registration
from crm.services import create_registration
from siteconfig.models import AppSettings, PrivacyStatement, SiteText

from . import ratelimit
from .forms import RegistrationForm


@require_http_methods(["GET", "POST"])
def register(request):
    settings = AppSettings.load()
    rate_limited = False
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if ratelimit.is_limited(request, settings.rate_limit_per_hour):
            rate_limited = True
        elif form.is_spam:
            # Honeypot filled in: pretend it worked, store nothing.
            ratelimit.record_hit(request)
            return redirect("public:thanks")
        elif form.is_valid():
            ratelimit.record_hit(request)
            with transaction.atomic():
                result = create_registration(form.cleaned_data, summary=form.summary(), source=Registration.Source.FORM)
                # Emails go out only once the registration is safely stored.
                transaction.on_commit(partial(emails.registration_submitted, result.registration.pk))
            request.session["registration_id"] = result.registration.pk
            return redirect("public:thanks")
    else:
        form = RegistrationForm()

    js_messages = {
        "words": _("%(words)s / %(limit)s words"),
        "words_over": _("%(words)s / %(limit)s words — please shorten your text"),
        "max_words": _("Please use at most %(limit)s words."),
        "step": _("Step %(n)s of %(total)s: %(title)s"),
        "choose": _("Please choose an option."),
        "tick": _("Please tick this box to continue."),
        "required": _("This field is required."),
        "email": _("Please enter a valid email address."),
        "student_number": _("A student number is exactly 6 digits, e.g. 123456."),
        "future_date": _("The hand-in date must be in the future."),
        "sending": _("Sending…"),
    }
    status = 429 if rate_limited else (400 if form.is_bound else 200)
    return render(request, "public/register.html", {
        "form": form,
        "rate_limited": rate_limited,
        "js_messages": js_messages,
        "texts": {key: SiteText.objects.filter(key=key).first() for key in ("form_intro", "minor_note", "coach_note", "graduation_approval_notice")},
    }, status=status)


def thanks(request):
    registration_id = request.session.pop("registration_id", None)
    return render(request, "public/thanks.html", {
        "text": SiteText.objects.filter(key="thank_you").first(),
        "registered": registration_id is not None,
    })


def privacy(request):
    statement = PrivacyStatement.current()
    return render(request, "public/privacy.html", {
        "statement": statement,
        "title": _("Privacy statement"),
    })
