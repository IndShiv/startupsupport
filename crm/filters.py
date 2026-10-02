"""Search and filters for the student and startup lists (also used by the export)."""

from django import forms
from django.db.models import Exists, OuterRef, Q
from django.utils.translation import gettext_lazy as _

from siteconfig.models import Domain, PipelineStage, StudyYear

from .models import Coach, GraduationTrack, Startup, Student, Tag

YES_NO_ANY = [("", _("Any")), ("yes", _("Yes")), ("no", _("No")), ("unknown", _("Unknown"))]
SCOPE = [("mine", _("My caseload")), ("all", _("Everyone"))]
STATUS = [("active", _("Active")), ("archived", _("Archived")), ("all", _("All"))]


def _words_query(q, fields):
    """Every word must match at least one of the fields."""
    query = Q()
    for word in q.split():
        word_q = Q()
        for field in fields:
            word_q |= Q(**{f"{field}__icontains": word})
        query &= word_q
    return query


def _bool_filter(qs, field, value):
    if value == "yes":
        return qs.filter(**{field: True})
    if value == "no":
        return qs.filter(**{field: False})
    if value == "unknown":
        return qs.filter(**{f"{field}__isnull": True})
    return qs


class BaseFilterForm(forms.Form):
    q = forms.CharField(label=_("Search"), required=False)
    scope = forms.ChoiceField(label=_("Show"), choices=SCOPE, required=False)
    status = forms.ChoiceField(label=_("Status"), choices=STATUS, required=False)
    domain = forms.ModelChoiceField(label=_("Domain"), queryset=Domain.objects.all(), required=False, empty_label=_("Any domain"))
    study_year = forms.ModelChoiceField(label=_("Study year"), queryset=StudyYear.objects.all(), required=False, empty_label=_("Any study year"))
    graduation = forms.ChoiceField(label=_("Graduation track"), choices=[("", _("Any")), ("yes", _("Yes")), ("no", _("No")), ("approval_missing", _("Approval missing"))], required=False)

    def __init__(self, data=None, *, coach=None, **kwargs):
        self.coach = coach
        data = data.copy() if data is not None else {}
        # Coaches see their own caseload by default; others (and admins without a coach profile) see everyone.
        data.setdefault("scope", "mine" if coach else "all")
        data.setdefault("status", "active")
        super().__init__(data, **kwargs)
        if not coach:
            self.fields["scope"].choices = [("all", _("Everyone"))]

    def value(self, name):
        if not self.is_valid():
            return None
        return self.cleaned_data.get(name)

    @property
    def active_filter_count(self):
        if not self.is_valid():
            return 0
        skip = {"q", "scope", "status"}
        return sum(1 for name, value in self.cleaned_data.items() if name not in skip and value)


class StudentFilterForm(BaseFilterForm):
    def filter(self, qs=None):
        qs = Student.objects.current() if qs is None else qs
        if not self.is_valid():
            return qs.filter(archived_at__isnull=True)
        d = self.cleaned_data
        if d["q"]:
            qs = qs.filter(_words_query(d["q"], ["first_name", "last_name", "email", "student_number", "phone"]))
        if d["scope"] == "mine" and self.coach:
            qs = qs.filter(Q(startups__assigned_coach=self.coach) | Q(registrations__intake_coach=self.coach))
        if d["status"] == "active":
            qs = qs.filter(archived_at__isnull=True)
        elif d["status"] == "archived":
            qs = qs.filter(archived_at__isnull=False)
        if d["domain"]:
            qs = qs.filter(domain=d["domain"])
        if d["study_year"]:
            qs = qs.filter(study_year=d["study_year"])
        if d["graduation"] == "yes":
            qs = qs.filter(study_year__is_graduation_track=True)
        elif d["graduation"] == "no":
            qs = qs.filter(study_year__is_graduation_track=False)
        elif d["graduation"] == "approval_missing":
            qs = qs.filter(graduation_tracks__approval=GraduationTrack.Approval.NOT_YET)
        return qs.distinct()


class StartupFilterForm(BaseFilterForm):
    stage = forms.ModelChoiceField(label=_("Stage"), queryset=PipelineStage.objects.all(), required=False, empty_label=_("Any stage"))
    coach_filter = forms.ModelChoiceField(label=_("Coach"), queryset=Coach.objects.all(), required=False, empty_label=_("Any coach"))
    no_coach = forms.BooleanField(label=_("No coach yet"), required=False)
    paying = forms.ChoiceField(label=_("Paying customers"), choices=YES_NO_ANY, required=False)
    validated = forms.ChoiceField(label=_("Idea validated"), choices=YES_NO_ANY, required=False)
    tags = forms.ModelMultipleChoiceField(label=_("Tags"), queryset=Tag.objects.all(), required=False, widget=forms.CheckboxSelectMultiple)

    def filter(self, qs=None):
        qs = Startup.objects.all() if qs is None else qs
        if not self.is_valid():
            return qs.filter(archived_at__isnull=True)
        d = self.cleaned_data
        if d["q"]:
            qs = qs.filter(_words_query(d["q"], ["name", "description", "kvk_number", "founders__first_name", "founders__last_name", "founders__student_number"]))
        if d["scope"] == "mine" and self.coach:
            qs = qs.filter(assigned_coach=self.coach)
        if d["status"] == "active":
            qs = qs.filter(archived_at__isnull=True)
        elif d["status"] == "archived":
            qs = qs.filter(archived_at__isnull=False)
        if d["stage"]:
            qs = qs.filter(stage=d["stage"])
        if d["coach_filter"]:
            qs = qs.filter(assigned_coach=d["coach_filter"])
        if d["no_coach"]:
            qs = qs.filter(assigned_coach__isnull=True)
        if d["domain"]:
            qs = qs.filter(founders__domain=d["domain"])
        if d["study_year"]:
            qs = qs.filter(founders__study_year=d["study_year"])
        on_track = GraduationTrack.objects.filter(startup=OuterRef("pk"))
        if d["graduation"] == "yes":
            qs = qs.filter(Exists(on_track))
        elif d["graduation"] == "no":
            qs = qs.exclude(Exists(on_track))
        elif d["graduation"] == "approval_missing":
            qs = qs.filter(Exists(on_track.filter(approval=GraduationTrack.Approval.NOT_YET)))
        qs = _bool_filter(qs, "has_paying_customers", d["paying"])
        qs = _bool_filter(qs, "idea_validated", d["validated"])
        for tag in d["tags"]:
            qs = qs.filter(tags=tag)  # all selected tags must be present
        return qs.distinct()
