from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from crm.intake import record_intake_held, schedule_intake, urgency
from crm.models import Notification, Registration
from siteconfig.models import AppSettings

from .forms import IntakeHeldForm, ScheduleIntakeForm
from .permissions import staff_required

TABS = {
    "waiting": gettext_lazy("Awaiting intake"),
    "scheduled": gettext_lazy("Scheduled"),
    "done": gettext_lazy("Done (last 60 days)"),
}


def _base_queryset():
    return Registration.objects.select_related(
        "student__domain", "student__study_year", "startup__stage", "startup__assigned_coach",
        "preferred_coach", "intake_coach", "graduation",
    )


def _mine_filter(user):
    coach = getattr(user, "coach", None)
    if coach is None:
        return Q(pk__in=[])
    return Q(preferred_coach=coach) | Q(intake_coach=coach) | Q(startup__assigned_coach=coach)


@staff_required
def home(request):
    return redirect("staff:intake_queue")


@staff_required
def intake_queue(request):
    tab = request.GET.get("tab", "waiting")
    if tab not in TABS:
        tab = "waiting"
    mine = request.GET.get("mine") == "1"
    settings = AppSettings.load()
    today = timezone.localdate()

    querysets = {
        "waiting": _base_queryset().awaiting_intake().order_by("intake_deadline", "submitted_at"),
        "scheduled": _base_queryset().intake_scheduled().order_by("intake_planned_at", "intake_scheduled_on"),
        "done": _base_queryset().intake_done().filter(intake_held_on__gte=today - timedelta(days=60)).order_by("-intake_held_on"),
    }
    if mine:
        querysets = {key: qs.filter(_mine_filter(request.user)) for key, qs in querysets.items()}
    counts = {key: qs.count() for key, qs in querysets.items()}

    rows = []
    for registration in querysets[tab]:
        row = {"registration": registration}
        if tab == "waiting" and registration.intake_deadline:
            row["urgency"] = urgency(registration, today, settings.intake_due_soon_days)
        if registration.intake_deadline and registration.intake_scheduled_on:
            row["on_time"] = registration.intake_scheduled_on <= registration.intake_deadline
        rows.append(row)
    if tab == "waiting":
        # Sorted by days remaining; the deadline order already gives this, but be explicit.
        rows.sort(key=lambda r: (r["urgency"].days_left if "urgency" in r else 999, r["registration"].submitted_at))

    overdue = sum(1 for r in rows if r.get("urgency") and r["urgency"].level == "overdue") if tab == "waiting" else None
    return render(request, "staff/intake_queue.html", {
        "tab": tab,
        "tab_list": [(key, label, counts[key]) for key, label in TABS.items()],
        "tab_label": TABS[tab],
        "rows": rows,
        "mine": mine,
        "has_coach": hasattr(request.user, "coach"),
        "overdue": overdue,
        "settings": settings,
    })


@staff_required
def intake_detail(request, pk):
    registration = get_object_or_404(_base_queryset(), pk=pk)
    action = request.POST.get("action") if request.method == "POST" else None
    schedule_form = ScheduleIntakeForm(request.POST if action == "schedule" else None, registration=registration, prefix="schedule")
    held_form = IntakeHeldForm(request.POST if action == "held" else None, registration=registration, prefix="held")

    if action:
        if action == "schedule":
            if schedule_form.is_valid():
                data = schedule_form.cleaned_data
                schedule_intake(registration, scheduled_on=data["scheduled_on"], planned_at=data["planned_at"],
                                coach=data["coach"], assign_coach=data["assign_coach"], user=request.user)
                messages.success(request, _("Intake scheduled for %(name)s.") % {"name": registration.student.full_name})
                return redirect("staff:intake_queue")
        elif action == "held":
            if held_form.is_valid():
                data = held_form.cleaned_data
                record_intake_held(registration, held_on=data["held_on"], coach=data["coach"],
                                   assign_coach=data["assigned_coach"], note=data["note"], user=request.user)
                messages.success(request, _("Intake recorded for %(name)s.") % {"name": registration.student.full_name})
                return redirect("staff:intake_queue")

    other_registrations = registration.student.registrations.exclude(pk=registration.pk).select_related("startup").order_by("-submitted_at")
    return render(request, "staff/intake_detail.html", {
        "r": registration,
        "urgency": urgency(registration) if registration.intake_deadline and not registration.intake_scheduled_on else None,
        "schedule_form": schedule_form,
        "held_form": held_form,
        "open_form": action,
        "other_registrations": other_registrations,
        "follow_ups": registration.student.follow_ups.filter(done_at__isnull=True),
    })


@staff_required
def notifications(request):
    items = request.user.notifications.all()[:100]
    return render(request, "staff/notifications.html", {"items": items})


@staff_required
@require_POST
def notifications_read(request):
    request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = "staff:notifications"
    return redirect(target)


@staff_required
def notification_open(request, pk):
    item = get_object_or_404(Notification, pk=pk, user=request.user)
    if item.read_at is None:
        item.read_at = timezone.now()
        item.save(update_fields=["read_at"])
    return redirect(item.url or "staff:notifications")
