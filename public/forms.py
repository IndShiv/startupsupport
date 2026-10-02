"""The registration form. Also reused by staff for walk-in registrations (step 5)."""

from django import forms
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _

from crm.models import DESCRIPTION_MAX_WORDS, GRADUATION_TOPIC_MAX_WORDS, Coach, GraduationTrack
from crm.validators import MaxWordsValidator, validate_phone, validate_student_number
from siteconfig.models import Domain, PrivacyStatement, StudyYear

YES_NO = [("yes", _("Yes")), ("no", _("No"))]
NO_PREFERENCE = "none"

# Sections in display order: (key, title, field names). The graduation section is only
# shown, validated and saved when the chosen study year is the graduation track.
SECTIONS = [
    ("about", _("About you"), ["first_name", "last_name", "student_number", "email", "phone", "domain", "study_year"]),
    ("business", _("Your business"), ["description", "has_paying_customers", "idea_validated", "goals"]),
    ("graduation", _("Graduating within your own company"), ["grad_approval", "grad_topic", "grad_supervisor", "grad_hand_in_date"]),
    ("coach", _("Your coach"), ["preferred_coach"]),
    ("finally", _("Finally"), ["comments", "privacy_consent"]),
]
GRADUATION_FIELDS = SECTIONS[2][2]


class OptionChoiceField(forms.ModelChoiceField):
    widget = forms.RadioSelect

    def label_from_instance(self, obj):
        return obj.name


class RegistrationForm(forms.Form):
    # About you
    first_name = forms.CharField(label=_("First name"), max_length=100, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(label=_("Last name"), max_length=100, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    student_number = forms.CharField(
        label=_("Student number"), max_length=20, required=False,
        help_text=_("6 digits, e.g. 123456. Optional if you are a BUas employee."),
        widget=forms.TextInput(attrs={"inputmode": "numeric", "pattern": r"\s*\d{6}\s*", "autocomplete": "off"}),
    )
    email = forms.EmailField(
        label=_("Email"), help_text=_("Preferably your BUas address (…@buas.nl)."),
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    phone = forms.CharField(
        label=_("Phone number"), max_length=20, validators=[validate_phone],
        help_text=_("Include the country code if you don't have a Dutch number, e.g. +32 470 12 34 56."),
        widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}),
    )
    domain = OptionChoiceField(label=_("Domain"), queryset=Domain.objects.none(), empty_label=None)
    study_year = OptionChoiceField(label=_("Study year"), queryset=StudyYear.objects.none(), empty_label=None)

    # Your business
    description = forms.CharField(
        label=_("Describe your business (idea)"),
        help_text=_("Maximum %(limit)d words.") % {"limit": DESCRIPTION_MAX_WORDS},
        validators=[MaxWordsValidator(DESCRIPTION_MAX_WORDS)],
        widget=forms.Textarea(attrs={"rows": 6, "data-max-words": DESCRIPTION_MAX_WORDS}),
    )
    has_paying_customers = forms.ChoiceField(label=_("Do you already have paying customers?"), choices=YES_NO, required=False, widget=forms.RadioSelect)
    idea_validated = forms.ChoiceField(label=_("Have you validated your idea in practice with your target customers?"), choices=YES_NO, required=False, widget=forms.RadioSelect)
    goals = forms.CharField(label=_("How can we help you? What are your goals for the coach track?"), widget=forms.Textarea(attrs={"rows": 5}))

    # Graduating within your own company (conditionally required)
    grad_approval = forms.ChoiceField(
        label=_("Do you have approval from your programme to graduate with your own company?"),
        choices=GraduationTrack.Approval.choices, required=False, widget=forms.RadioSelect,
    )
    grad_topic = forms.CharField(
        label=_("Graduation assignment topic"), required=False,
        help_text=_("Maximum %(limit)d words.") % {"limit": GRADUATION_TOPIC_MAX_WORDS},
        validators=[MaxWordsValidator(GRADUATION_TOPIC_MAX_WORDS)],
        widget=forms.Textarea(attrs={"rows": 4, "data-max-words": GRADUATION_TOPIC_MAX_WORDS}),
    )
    grad_supervisor = forms.CharField(label=_("Name of graduation supervisor"), max_length=200, required=False)
    grad_hand_in_date = forms.DateField(
        label=_("Intended hand-in date of final product"), required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    # Your coach
    preferred_coach = forms.ChoiceField(label=_("Preferred coach"), widget=forms.RadioSelect)

    # Finally
    comments = forms.CharField(label=_("Comments / anything else we should know"), required=False, widget=forms.Textarea(attrs={"rows": 4}))
    privacy_consent = forms.BooleanField(
        label=_("I have read the privacy statement and agree that BUSS stores and uses my data as described there."),
        error_messages={"required": _("Please agree to the privacy statement to register.")},
    )
    privacy_version = forms.ModelChoiceField(queryset=PrivacyStatement.objects.filter(published_at__isnull=False), widget=forms.HiddenInput)

    # Honeypot: hidden from people (and screen readers), bots tend to fill it in.
    website = forms.CharField(required=False, label=_("Leave this field empty"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["domain"].queryset = Domain.objects.filter(active=True)
        self.fields["study_year"].queryset = StudyYear.objects.filter(active=True)
        self.coaches = list(Coach.objects.filter(active=True).prefetch_related("domains"))
        self.fields["preferred_coach"].choices = [(str(c.pk), c.full_name) for c in self.coaches] + [
            (NO_PREFERENCE, _("No preference, I trust you to make the best match"))
        ]
        current = PrivacyStatement.current()
        if current and not self.is_bound:
            self.initial.setdefault("privacy_version", current.pk)
        self.privacy_statement = current
        self.employee_domain_ids = [str(pk) for pk in Domain.objects.filter(is_employee=True).values_list("pk", flat=True)]
        self.graduation_year_ids = [str(pk) for pk in StudyYear.objects.filter(is_graduation_track=True).values_list("pk", flat=True)]

    # Fields marked with * on the form. Student number and the graduation fields are
    # conditionally required: clean() enforces them, register.js toggles `required`.
    STAR_FIELDS = ["first_name", "last_name", "student_number", "email", "phone", "domain", "study_year",
                   "description", "goals", "preferred_coach", "privacy_consent"] + GRADUATION_FIELDS

    # -- field cleaning ---------------------------------------------------
    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()

    def clean_student_number(self):
        value = self.cleaned_data["student_number"].replace(" ", "")
        validate_student_number(value)
        return value

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_phone(self):
        return " ".join(self.cleaned_data["phone"].split())

    def clean_grad_hand_in_date(self):
        value = self.cleaned_data.get("grad_hand_in_date")
        if value and value <= timezone.localdate():
            raise forms.ValidationError(_("The hand-in date must be in the future."))
        return value

    def clean_preferred_coach(self):
        value = self.cleaned_data["preferred_coach"]
        if value == NO_PREFERENCE:
            return None
        return next(c for c in self.coaches if str(c.pk) == value)

    def clean(self):
        data = super().clean()
        domain = data.get("domain")
        if domain is not None and not domain.is_employee and not data.get("student_number") and "student_number" not in self.errors:
            self.add_error("student_number", _("Please enter your student number."))

        study_year = data.get("study_year")
        if study_year is not None and study_year.is_graduation_track:
            messages = {
                "grad_approval": _("Please tell us whether you have approval from your programme."),
                "grad_topic": _("Please describe your graduation assignment topic."),
                "grad_supervisor": _("Please enter the name of your graduation supervisor."),
                "grad_hand_in_date": _("Please choose your intended hand-in date."),
            }
            for name, message in messages.items():
                if not data.get(name) and name not in self.errors:
                    self.add_error(name, message)
        else:
            # Not on the graduation track: ignore anything posted for that section.
            for name in GRADUATION_FIELDS:
                self.errors.pop(name, None)
                data[name] = None
        return data

    # -- helpers for the template and the service -------------------------
    @property
    def is_spam(self):
        return bool(self.data.get("website"))

    @property
    def on_graduation_track(self):
        year = self.cleaned_data.get("study_year") if hasattr(self, "cleaned_data") else None
        return bool(year and year.is_graduation_track)

    def sections(self):
        for key, title, names in SECTIONS:
            yield {"key": key, "title": title, "fields": [self[name] for name in names],
                   "has_errors": any(self[name].errors for name in names)}

    def summary(self):
        """[(section title, [(label, value), ...]), ...] of the answers, for records and emails."""
        data = self.cleaned_data
        yes_no = {"yes": str(_("Yes")), "no": str(_("No")), "": "–", None: "–"}
        values = {
            "first_name": data["first_name"],
            "last_name": data["last_name"],
            "student_number": data["student_number"] or "–",
            "email": data["email"],
            "phone": data["phone"],
            "domain": data["domain"].name,
            "study_year": data["study_year"].name,
            "description": data["description"],
            "has_paying_customers": yes_no[data.get("has_paying_customers")],
            "idea_validated": yes_no[data.get("idea_validated")],
            "goals": data["goals"],
            "preferred_coach": data["preferred_coach"].full_name if data["preferred_coach"] else str(_("No preference")),
            "comments": data["comments"] or "–",
            "privacy_consent": str(_("Yes")),
        }
        if self.on_graduation_track:
            values.update({
                "grad_approval": str(GraduationTrack.Approval(data["grad_approval"]).label),
                "grad_topic": data["grad_topic"],
                "grad_supervisor": data["grad_supervisor"],
                "grad_hand_in_date": date_format(data["grad_hand_in_date"], "j F Y"),
            })
        result = []
        for key, title, names in SECTIONS:
            rows = [(str(self.fields[n].label), values[n]) for n in names if n in values]
            if rows:
                result.append((str(title), rows))
        return result
