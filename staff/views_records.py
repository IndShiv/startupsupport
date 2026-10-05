"""Students, startups and walk-in registrations."""

from functools import partial

from auditlog.models import LogEntry
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from crm import emails
from crm.filters import StartupFilterForm, StudentFilterForm
from crm.models import Founder, GraduationTrack, Registration, Startup, Student
from crm.services import create_registration, duplicate_candidates, merge_students
from siteconfig.models import PipelineStage

from .forms import ActivityForm, FounderForm, GraduationTrackForm, StartupForm, StudentForm, WalkInForm
from .permissions import is_admin, staff_required
from .views_activity import can_edit_activity

PAGE_SIZE = 50


def _coach(user):
    return getattr(user, "coach", None)


def _page(request, qs):
    return Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))


def _history(obj, limit=15):
    return LogEntry.objects.get_for_object(obj).select_related("actor")[:limit]


def _querystring_without_page(request):
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


# -- students ----------------------------------------------------------------------------

@staff_required
def student_list(request):
    form = StudentFilterForm(request.GET, coach=_coach(request.user))
    qs = form.filter().select_related("domain", "study_year").annotate(
        idea_count=Count("startups", distinct=True),
        last_registration=Max("registrations__submitted_at"),
    ).order_by("last_name", "first_name")
    return render(request, "staff/student_list.html", {
        "form": form, "page": _page(request, qs), "qs": _querystring_without_page(request),
    })


@staff_required
def student_detail(request, pk):
    student = get_object_or_404(Student.objects.select_related("domain", "study_year", "merged_into"), pk=pk)
    startups = student.startups.select_related("stage", "assigned_coach").prefetch_related(
        Prefetch("founder_links", queryset=Founder.objects.select_related("student"))
    )
    return render(request, "staff/student_detail.html", {
        "s": student,
        "startups": startups,
        "registrations": student.registrations.select_related("startup", "intake_coach").order_by("-submitted_at"),
        "tracks": student.graduation_tracks.select_related("startup"),
        "follow_ups": student.follow_ups.open().select_related("assigned_to").order_by("due_date"),
        "followup_qs": f"student={student.pk}",
        "today": timezone.localdate(),
        "merged_from": student.merged_from.all(),
        "candidates": duplicate_candidates(student) if is_admin(request.user) and not student.merged_into_id else [],
        "history": _history(student),
    })


@staff_required
def student_edit(request, pk):
    student = get_object_or_404(Student.objects.current(), pk=pk)
    form = StudentForm(request.POST or None, instance=student)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Changes saved."))
        return redirect("staff:student_detail", pk=student.pk)
    return render(request, "staff/record_form.html", {
        "form": form, "title": _("Edit %(name)s") % {"name": student.full_name},
        "back": ("staff:student_detail", student.pk),
    })


@staff_required
@require_POST
def student_archive(request, pk):
    student = get_object_or_404(Student.objects.current(), pk=pk)
    student.archived_at = None if student.archived_at else timezone.now()
    student.save(update_fields=["archived_at", "updated_at"])
    messages.success(request, _("Student archived.") if student.archived_at else _("Student restored."))
    return redirect("staff:student_detail", pk=pk)


@staff_required
def student_merge(request, pk, other_pk):
    """Merge `other` (the duplicate) into `pk` (the record to keep). Admins only."""
    if not is_admin(request.user):
        raise PermissionDenied
    target = get_object_or_404(Student.objects.current(), pk=pk)
    duplicate = get_object_or_404(Student.objects.current(), pk=other_pk)
    if target.pk == duplicate.pk:
        raise PermissionDenied
    if request.method == "POST":
        merge_students(target, duplicate)
        messages.success(request, _("%(dup)s has been merged into this record.") % {"dup": duplicate.full_name})
        return redirect("staff:student_detail", pk=target.pk)
    fields = ["first_name", "last_name", "student_number", "email", "phone", "domain", "study_year"]
    rows = [(Student._meta.get_field(f).verbose_name, getattr(target, f), getattr(duplicate, f)) for f in fields]
    return render(request, "staff/student_merge.html", {
        "target": target, "duplicate": duplicate, "rows": rows,
        "moving": {
            "registrations": duplicate.registrations.count(),
            "startups": duplicate.startups.count(),
            "follow_ups": duplicate.follow_ups.count(),
        },
    })


@staff_required
def student_merge_search(request, pk):
    if not is_admin(request.user):
        raise PermissionDenied
    target = get_object_or_404(Student.objects.current(), pk=pk)
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        form = StudentFilterForm({"q": q, "scope": "all", "status": "all"})
        results = form.filter().exclude(pk=target.pk).select_related("domain")[:20]
    return render(request, "staff/student_merge_search.html", {"target": target, "q": q, "results": results})


# -- startups ----------------------------------------------------------------------------

@staff_required
def startup_list(request):
    form = StartupFilterForm(request.GET, coach=_coach(request.user))
    qs = form.filter().select_related("stage", "assigned_coach").prefetch_related("founders", "tags").order_by("-created_at")
    return render(request, "staff/startup_list.html", {
        "form": form, "page": _page(request, qs), "qs": _querystring_without_page(request),
    })


@staff_required
def startup_detail(request, pk, activity_form=None):
    startup = get_object_or_404(Startup.objects.select_related("stage", "assigned_coach"), pk=pk)
    activities = startup.activities.select_related("author")
    if not is_admin(request.user):
        activities = activities.filter(admin_only=False)
    founder_q = request.GET.get("founder_q", "").strip()
    founder_results = []
    if founder_q:
        form = StudentFilterForm({"q": founder_q, "scope": "all", "status": "active"})
        founder_results = form.filter().exclude(startups=startup)[:10]
    return render(request, "staff/startup_detail.html", {
        "st": startup,
        "founder_links": startup.founder_links.select_related("student__domain", "student__study_year"),
        "registrations": startup.registrations.select_related("student").order_by("-submitted_at"),
        "tracks": startup.graduation_tracks.select_related("student"),
        "activities": [(a, can_edit_activity(request.user, a)) for a in activities[: 200 if request.GET.get("all") else 30]],
        "activity_count": activities.count(),
        "show_all": bool(request.GET.get("all")),
        "activity_form": activity_form or ActivityForm(user_is_admin=is_admin(request.user), prefix="activity"),
        "follow_ups": startup.follow_ups.open().select_related("assigned_to").order_by("due_date"),
        "today": timezone.localdate(),
        "followup_qs": f"startup={startup.pk}",
        "founder_q": founder_q,
        "founder_results": founder_results,
        "history": _history(startup),
    })


@staff_required
def startup_edit(request, pk=None):
    startup = get_object_or_404(Startup, pk=pk) if pk else None
    student = None
    if startup is None:
        student = get_object_or_404(Student.objects.current(), pk=request.GET.get("student") or request.POST.get("student"))
        startup = Startup(stage=PipelineStage.initial())
    form = StartupForm(request.POST or None, instance=startup)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            if student:
                Founder.objects.create(startup=startup, student=student)
        messages.success(request, _("Changes saved.") if pk else _("Idea added."))
        return redirect("staff:startup_detail", pk=startup.pk)
    title = _("Edit %(name)s") % {"name": startup.display_name} if pk else _("New idea for %(name)s") % {"name": student.full_name}
    back = ("staff:startup_detail", startup.pk) if pk else ("staff:student_detail", student.pk)
    return render(request, "staff/record_form.html", {"form": form, "title": title, "back": back, "student": student})


@staff_required
@require_POST
def startup_archive(request, pk):
    startup = get_object_or_404(Startup, pk=pk)
    startup.archived_at = None if startup.archived_at else timezone.now()
    startup.save(update_fields=["archived_at", "updated_at"])
    messages.success(request, _("Startup archived.") if startup.archived_at else _("Startup restored."))
    return redirect("staff:startup_detail", pk=pk)


@staff_required
@require_POST
def founder_add(request, pk):
    startup = get_object_or_404(Startup, pk=pk)
    form = FounderForm(request.POST)
    if form.is_valid():
        Founder.objects.get_or_create(startup=startup, student=form.cleaned_data["student"], defaults={"role": form.cleaned_data["role"]})
        messages.success(request, _("%(name)s added as founder.") % {"name": form.cleaned_data["student"].full_name})
    else:
        messages.error(request, _("Could not add this founder."))
    return redirect("staff:startup_detail", pk=pk)


@staff_required
@require_POST
def founder_remove(request, pk, founder_pk):
    link = get_object_or_404(Founder, pk=founder_pk, startup_id=pk)
    if link.startup.founder_links.count() <= 1:
        messages.error(request, _("A startup needs at least one founder."))
    else:
        link.delete()
        messages.success(request, _("Founder removed."))
    return redirect("staff:startup_detail", pk=pk)


@staff_required
def graduation_edit(request, pk):
    track = get_object_or_404(GraduationTrack.objects.select_related("student", "startup"), pk=pk)
    form = GraduationTrackForm(request.POST or None, instance=track)
    if request.method == "POST" and form.is_valid():
        track = form.save()
        if not track.approval_missing:
            # Approval arrived: close the automatic reminder.
            track.student.follow_ups.filter(auto_reason="graduation_approval_missing", done_at__isnull=True).update(done_at=timezone.now())
        messages.success(request, _("Graduation details saved."))
        return redirect("staff:startup_detail", pk=track.startup_id)
    return render(request, "staff/record_form.html", {
        "form": form, "title": _("Graduation track of %(name)s") % {"name": track.student.full_name},
        "back": ("staff:startup_detail", track.startup_id),
    })


# -- walk-ins ----------------------------------------------------------------------------

@staff_required
def walk_in(request):
    form = WalkInForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            result = create_registration(form.cleaned_data, summary=form.summary(), source=Registration.Source.WALK_IN, created_by=request.user)
            transaction.on_commit(partial(
                emails.registration_submitted, result.registration.pk,
                confirm_to_student=form.cleaned_data["send_confirmation"], notify_staff=False,
            ))
        if result.is_duplicate:
            messages.warning(request, _("This student was already known; the new idea has been linked to the existing record."))
        else:
            messages.success(request, _("Walk-in registered."))
        return redirect("staff:intake_detail", pk=result.registration.pk)
    return render(request, "staff/walk_in.html", {"form": form})
