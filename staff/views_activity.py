"""Activity log entries and follow-ups."""

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from crm.models import Activity, FollowUp, Startup, Student

from .context_processors import end_of_week
from .forms import ActivityForm, FollowUpForm
from .permissions import is_admin, staff_required


def _next(request, default):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return default


def _default_assignee(startup, user):
    coach = startup.assigned_coach if startup else None
    return coach.user if coach and coach.user_id else user


def can_edit_activity(user, activity):
    if activity.kind in Activity.SYSTEM_KINDS:
        return False
    return is_admin(user) or activity.author_id == user.pk


# -- activity log -----------------------------------------------------------------------------

@staff_required
@require_POST
def activity_add(request, pk):
    startup = get_object_or_404(Startup, pk=pk)
    form = ActivityForm(request.POST, user_is_admin=is_admin(request.user), prefix="activity")
    if form.is_valid():
        with transaction.atomic():
            activity = form.save(commit=False)
            activity.startup = startup
            activity.author = request.user
            activity.save()
            if form.cleaned_data.get("follow_up_title"):
                FollowUp.objects.create(
                    startup=startup, title=form.cleaned_data["follow_up_title"], due_date=form.cleaned_data["follow_up_due"],
                    assigned_to=_default_assignee(startup, request.user), created_by=request.user,
                )
        messages.success(request, _("Added to the activity log."))
        return redirect(reverse("staff:startup_detail", args=[pk]) + "#activity")
    # Show the startup page again with the errors and the typed text kept.
    from .views_records import startup_detail

    return startup_detail(request, pk, activity_form=form)


@staff_required
def activity_edit(request, pk):
    activity = get_object_or_404(Activity.objects.select_related("startup"), pk=pk)
    if not can_edit_activity(request.user, activity):
        raise PermissionDenied
    form = ActivityForm(request.POST or None, instance=activity, user_is_admin=is_admin(request.user), with_follow_up=False)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Activity updated."))
        return redirect(reverse("staff:startup_detail", args=[activity.startup_id]) + "#activity")
    return render(request, "staff/record_form.html", {
        "form": form, "title": _("Edit activity"), "back": ("staff:startup_detail", activity.startup_id),
        "delete_url": reverse("staff:activity_delete", args=[activity.pk]),
    })


@staff_required
@require_POST
def activity_delete(request, pk):
    activity = get_object_or_404(Activity, pk=pk)
    if not can_edit_activity(request.user, activity):
        raise PermissionDenied
    startup_id = activity.startup_id
    activity.delete()
    messages.success(request, _("Activity deleted."))
    return redirect(reverse("staff:startup_detail", args=[startup_id]) + "#activity")


# -- follow-ups -------------------------------------------------------------------------------

TABS = {
    "week": gettext_lazy("This week"),
    "upcoming": gettext_lazy("Later"),
    "done": gettext_lazy("Done (last 30 days)"),
}


@staff_required
def followup_list(request):
    user = request.user
    tab = request.GET.get("tab", "week")
    if tab not in TABS:
        tab = "week"
    scopes = {"mine": _("Mine"), "all": _("Everyone")}
    if is_admin(user):
        scopes["unassigned"] = _("Unassigned")
    scope = request.GET.get("scope", "mine")
    if scope not in scopes:
        scope = "mine"

    qs = FollowUp.objects.select_related("startup__assigned_coach", "student", "assigned_to")
    if scope == "mine":
        qs = qs.for_user(user)
    elif scope == "unassigned":
        qs = qs.filter(assigned_to__isnull=True)

    today = timezone.localdate()
    week_end = end_of_week(today)
    if tab == "week":
        items = qs.open().due_by(week_end).order_by("due_date", "pk")
    elif tab == "upcoming":
        items = qs.open().filter(due_date__gt=week_end).order_by("due_date", "pk")
    else:
        items = qs.filter(done_at__gte=timezone.now() - timedelta(days=30)).order_by("-done_at")

    return render(request, "staff/followups.html", {
        "tab": tab, "tabs": TABS, "scope": scope, "scopes": scopes,
        "items": items, "today": today, "week_end": week_end,
        "overdue": sum(1 for f in items if tab == "week" and f.due_date < today),
    })


@staff_required
def followup_create(request):
    startup = get_object_or_404(Startup, pk=request.GET["startup"]) if request.GET.get("startup") else None
    student = get_object_or_404(Student, pk=request.GET["student"]) if request.GET.get("student") else None
    if not (startup or student):
        raise PermissionDenied
    form = FollowUpForm(request.POST or None, initial={
        "assigned_to": _default_assignee(startup, request.user),
        "due_date": timezone.localdate() + timedelta(days=7),
    })
    if request.method == "POST" and form.is_valid():
        follow_up = form.save(commit=False)
        follow_up.startup, follow_up.student, follow_up.created_by = startup, student, request.user
        follow_up.save()
        messages.success(request, _("Follow-up added."))
        default = reverse("staff:startup_detail", args=[startup.pk]) if startup else reverse("staff:student_detail", args=[student.pk])
        return redirect(_next(request, default))
    subject = startup.display_name if startup else student.full_name
    back = ("staff:startup_detail", startup.pk) if startup else ("staff:student_detail", student.pk)
    return render(request, "staff/record_form.html", {"form": form, "title": _("New follow-up: %(subject)s") % {"subject": subject}, "back": back})


@staff_required
def followup_edit(request, pk):
    follow_up = get_object_or_404(FollowUp, pk=pk)
    form = FollowUpForm(request.POST or None, instance=follow_up)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Follow-up updated."))
        return redirect(_next(request, reverse("staff:followups")))
    back = ("staff:startup_detail", follow_up.startup_id) if follow_up.startup_id else ("staff:student_detail", follow_up.student_id)
    return render(request, "staff/record_form.html", {"form": form, "title": _("Edit follow-up"), "back": back})


@staff_required
@require_POST
def followup_done(request, pk):
    follow_up = get_object_or_404(FollowUp, pk=pk)
    follow_up.done_at = None if follow_up.done_at else timezone.now()
    follow_up.save(update_fields=["done_at"])
    if follow_up.done_at:
        messages.success(request, _("Marked as done: %(title)s") % {"title": follow_up.title})
    else:
        messages.success(request, _("Reopened: %(title)s") % {"title": follow_up.title})
    return redirect(_next(request, reverse("staff:followups")))


@staff_required
@require_POST
def followup_snooze(request, pk):
    follow_up = get_object_or_404(FollowUp, pk=pk, done_at__isnull=True)
    base = max(follow_up.due_date, timezone.localdate())
    follow_up.due_date = base + timedelta(days=7)
    follow_up.save(update_fields=["due_date"])
    messages.success(request, _("Moved to %(date)s.") % {"date": date_format(follow_up.due_date, "j F")})
    return redirect(_next(request, reverse("staff:followups")))
