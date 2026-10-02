from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from crm.intake import coaches_with_caseload, domain_conflict


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
