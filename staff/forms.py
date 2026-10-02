from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from crm.intake import coaches_with_caseload, conflicting_students, domain_conflict
from crm.models import GraduationTrack, Startup, Student, Tag
from public.forms import RegistrationForm


class CoachChoiceField(forms.ModelChoiceField):
    """Coach dropdown showing each coach's current caseload and a same-domain warning."""

    def __init__(self, *args, registration=None, **kwargs):
        self.registration = registration
        super().__init__(coaches_with_caseload(), *args, **kwargs)

    def label_from_instance(self, coach):
        n = coach.active_caseload
        label = f"{coach.full_name} · " + ngettext("%(n)d active startup", "%(n)d active startups", n) % {"n": n}
        if self.registration and domain_conflict(self.registration, coach):
            label += " · ⚠ " + str(_("same domain as student"))
        return label


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class DomainCheckMixin:
    """Graduation-track students need a coach from another domain; allow an explicit override."""

    domain_field = None

    def check_domain(self, coach_field):
        coach = self.cleaned_data.get(coach_field)
        if coach and domain_conflict(self.registration, coach) and not self.cleaned_data.get("confirm_domain"):
            self.domain_warning = True
            self.add_error(coach_field, _(
                "%(coach)s is from the student's own domain, but graduation-track students are matched with a coach "
                "from a different domain. Choose another coach, or tick the box below to confirm."
            ) % {"coach": coach.full_name})

    domain_warning = False


class ScheduleIntakeForm(DomainCheckMixin, forms.Form):
    scheduled_on = forms.DateField(label=_("Intake arranged on"), widget=DateInput(), help_text=_("The day you contacted the student and agreed on the intake. This stops the 10-working-day clock."))
    planned_at = forms.DateTimeField(label=_("Intake planned for"), required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))
    coach = CoachChoiceField(label=_("Intake by"), required=True)
    assign_coach = forms.BooleanField(label=_("Also make this coach the student's coach"), required=False)
    confirm_domain = forms.BooleanField(label=_("I know this coach is from the student's own domain, assign anyway"), required=False)

    def __init__(self, *args, registration, **kwargs):
        self.registration = registration
        initial = kwargs.setdefault("initial", {})
        initial.setdefault("scheduled_on", registration.intake_scheduled_on or timezone.localdate())
        initial.setdefault("planned_at", registration.intake_planned_at and timezone.localtime(registration.intake_planned_at))
        initial.setdefault("coach", registration.intake_coach or registration.startup.assigned_coach or registration.preferred_coach)
        initial.setdefault("assign_coach", registration.startup.assigned_coach is None)
        super().__init__(*args, **kwargs)
        self.fields["coach"] = CoachChoiceField(label=_("Intake by"), registration=registration)

    def clean_scheduled_on(self):
        value = self.cleaned_data["scheduled_on"]
        if value > timezone.localdate():
            raise forms.ValidationError(_("This date cannot be in the future: it is the day the intake was arranged."))
        if value < timezone.localdate(self.registration.submitted_at):
            raise forms.ValidationError(_("This date cannot be before the registration."))
        return value

    def clean(self):
        data = super().clean()
        if data.get("assign_coach"):
            self.check_domain("coach")
        return data


class IntakeHeldForm(DomainCheckMixin, forms.Form):
    held_on = forms.DateField(label=_("Intake held on"), widget=DateInput())
    coach = CoachChoiceField(label=_("Intake held by"))
    assigned_coach = CoachChoiceField(label=_("Coach for the coaching track"), required=False, help_text=_("Leave empty if this is not decided yet."))
    note = forms.CharField(label=_("Intake notes"), required=False, widget=forms.Textarea(attrs={"rows": 4}), help_text=_("Saved in the activity log of the startup."))
    confirm_domain = forms.BooleanField(label=_("I know this coach is from the student's own domain, assign anyway"), required=False)

    def __init__(self, *args, registration, **kwargs):
        self.registration = registration
        initial = kwargs.setdefault("initial", {})
        initial.setdefault("held_on", timezone.localdate())
        initial.setdefault("coach", registration.intake_coach or registration.startup.assigned_coach)
        initial.setdefault("assigned_coach", registration.startup.assigned_coach or registration.intake_coach)
        super().__init__(*args, **kwargs)
        self.fields["coach"] = CoachChoiceField(label=_("Intake held by"), registration=registration)
        self.fields["assigned_coach"] = CoachChoiceField(
            label=_("Coach for the coaching track"), registration=registration, required=False,
            help_text=_("Leave empty if this is not decided yet."),
        )

    def clean_held_on(self):
        value = self.cleaned_data["held_on"]
        if value > timezone.localdate():
            raise forms.ValidationError(_("An intake cannot be recorded as held in the future."))
        if value < timezone.localdate(self.registration.submitted_at):
            raise forms.ValidationError(_("This date cannot be before the registration."))
        return value

    def clean(self):
        data = super().clean()
        self.check_domain("assigned_coach")
        return data


# -- records ---------------------------------------------------------------------------

YES_NO_UNKNOWN = [("", _("Unknown")), ("true", _("Yes")), ("false", _("No"))]


class NullBooleanSelect(forms.Select):
    def __init__(self):
        super().__init__(choices=YES_NO_UNKNOWN)

    def format_value(self, value):
        return {True: "true", False: "false"}.get(value, "")

    def value_from_datadict(self, data, files, name):
        return {"true": True, "false": False}.get(data.get(name))


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["first_name", "last_name", "student_number", "email", "phone", "domain", "study_year"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student_number"].help_text = _("6 digits. Optional for employees.")
        self.fields["domain"].empty_label = None
        self.fields["study_year"].empty_label = None

    def clean_student_number(self):
        value = self.cleaned_data["student_number"].replace(" ", "")
        if value:
            clash = Student.objects.current().filter(student_number=value).exclude(pk=self.instance.pk).first()
            if clash:
                raise forms.ValidationError(_("%(name)s already has this student number. If this is the same person, merge the two records instead.") % {"name": clash.full_name})
        return value

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        data = super().clean()
        domain = data.get("domain")
        if domain and not domain.is_employee and not data.get("student_number") and "student_number" not in self.errors:
            self.add_error("student_number", _("A student number is required for students (optional for employees)."))
        return data


class StartupForm(forms.ModelForm):
    assigned_coach = CoachChoiceField(label=_("Coach"), required=False)
    new_tags = forms.CharField(label=_("New tags"), required=False, help_text=_("Comma-separated, e.g. “sustainability, funding needed”."))
    confirm_domain = forms.BooleanField(label=_("I know this coach is from a graduation-track founder's own domain, assign anyway"), required=False)

    class Meta:
        model = Startup
        fields = ["name", "description", "goals", "stage", "assigned_coach", "has_paying_customers", "idea_validated", "kvk_number", "tags"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "goals": forms.Textarea(attrs={"rows": 4}),
            "has_paying_customers": NullBooleanSelect(),
            "idea_validated": NullBooleanSelect(),
            "tags": forms.CheckboxSelectMultiple,
        }

    domain_warning = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].empty_label = None
        self.fields["kvk_number"].help_text = _("8 digits.")
        founders = list(self.instance.founders.select_related("study_year")) if self.instance.pk else []
        self.founders = founders
        field = self.fields["assigned_coach"]
        field.label_from_instance = lambda coach: self._coach_label(coach)

    def _coach_label(self, coach):
        n = coach.active_caseload
        label = f"{coach.full_name} · " + ngettext("%(n)d active startup", "%(n)d active startups", n) % {"n": n}
        if conflicting_students(self.founders, coach):
            label += " · ⚠ " + str(_("same domain as a graduation-track founder"))
        return label

    def clean_kvk_number(self):
        value = self.cleaned_data["kvk_number"].replace(" ", "")
        if value and not (value.isdigit() and len(value) == 8):
            raise forms.ValidationError(_("A KvK number is 8 digits."))
        return value

    def clean(self):
        data = super().clean()
        coach = data.get("assigned_coach")
        # Only warn when the coach changes; an existing assignment was already confirmed.
        changed = coach is not None and coach.pk != self.initial.get("assigned_coach")
        clash = conflicting_students(self.founders, coach) if changed else []
        if clash and not data.get("confirm_domain"):
            self.domain_warning = True
            self.add_error("assigned_coach", _(
                "%(coach)s is from the own domain of %(names)s, who graduates within their own company. "
                "Choose another coach, or tick the box below to confirm."
            ) % {"coach": coach.full_name, "names": ", ".join(s.full_name for s in clash)})
        return data

    def save(self, commit=True):
        startup = super().save(commit)
        names = [n.strip() for n in self.cleaned_data.get("new_tags", "").split(",") if n.strip()]
        if names and commit:
            for name in names:
                tag = Tag.objects.filter(name__iexact=name).first() or Tag.objects.create(name=name[:50])
                startup.tags.add(tag)
        return startup


class GraduationTrackForm(forms.ModelForm):
    class Meta:
        model = GraduationTrack
        fields = ["approval", "topic", "supervisor_name", "hand_in_date"]
        widgets = {"hand_in_date": DateInput(), "topic": forms.Textarea(attrs={"rows": 3})}


class FounderForm(forms.Form):
    student = forms.ModelChoiceField(label=_("Student"), queryset=Student.objects.current())
    role = forms.CharField(label=_("Role"), max_length=100, required=False, help_text=_("e.g. Co-founder, CTO"))


class WalkInForm(RegistrationForm):
    """The public registration form, filled in by staff for a student who walked in."""

    send_confirmation = forms.BooleanField(label=_("Email the student a confirmation with a summary"), required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["website"]
        self.fields["privacy_consent"].label = _("The student has been informed about the privacy statement and agrees to it.")
        self.fields["privacy_consent"].error_messages["required"] = _("Please confirm that the student agrees to the privacy statement.")
        self.fields["preferred_coach"].widget = forms.Select(choices=self.fields["preferred_coach"].choices)

    @property
    def is_spam(self):
        return False
