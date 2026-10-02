"""Pipeline: board (drag and drop) and list view of startups per stage."""

from datetime import timedelta

from django.contrib import messages
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from crm.filters import StartupFilterForm
from crm.intake import move_to_stage, pending_intake
from crm.models import GraduationTrack, Startup
from siteconfig.models import AppSettings, PipelineStage

from .permissions import staff_required


def _card(startup, stale_before):
    tracks = list(startup.graduation_tracks.all())
    return {
        "startup": startup,
        "founders": list(startup.founders.all()),
        "tags": list(startup.tags.all()),
        "graduation": bool(tracks),
        "approval_missing": any(t.approval_missing for t in tracks),
        "stale": (startup.last_activity_at or startup.created_at) < stale_before,
    }


@staff_required
def pipeline(request):
    view = "list" if request.GET.get("view") == "list" else "board"
    show_closed = request.GET.get("closed") == "1"
    form = StartupFilterForm(request.GET, coach=getattr(request.user, "coach", None))
    startups = form.filter().select_related("stage", "assigned_coach").prefetch_related(
        "founders", "tags", Prefetch("graduation_tracks", queryset=GraduationTrack.objects.only("pk", "startup_id", "approval")),
    ).order_by("-last_activity_at", "-created_at")

    settings = AppSettings.load()
    stale_before = timezone.now() - timedelta(weeks=settings.inactivity_weeks)
    cards = [_card(s, stale_before) for s in startups]

    # Active stages, plus inactive ones that still hold startups (so nothing disappears from view).
    used_stage_ids = {c["startup"].stage_id for c in cards}
    stages = [s for s in PipelineStage.objects.order_by("order", "name") if s.active or s.pk in used_stage_ids]
    columns = []
    for stage in stages:
        stage_cards = [c for c in cards if c["startup"].stage_id == stage.pk]
        columns.append({
            "stage": stage,
            "cards": stage_cards,
            "count": len(stage_cards),
            "collapsed": stage.is_closed and not show_closed,
        })

    params = request.GET.copy()
    for key in ("view", "closed"):
        params.pop(key, None)
    return render(request, "staff/pipeline.html", {
        "view": view,
        "form": form,
        "columns": columns,
        "cards": cards,
        "stages": stages,
        "show_closed": show_closed,
        "filter_qs": params.urlencode(),
        "inactivity_weeks": settings.inactivity_weeks,
        "total": len(cards),
        "js_messages": {
            "moving": _("Moving %(startup)s to %(stage)s…"),
            "failed": _("Could not move %(startup)s. Please try again."),
            "open_intake": _("Open intake page"),
        },
    })


@staff_required
@require_POST
def move(request, pk):
    startup = get_object_or_404(Startup.objects.select_related("stage"), pk=pk, archived_at__isnull=True)
    wants_json = request.headers.get("Accept", "").startswith("application/json")
    try:
        stage = PipelineStage.objects.get(pk=int(request.POST.get("stage", "")))
    except (ValueError, PipelineStage.DoesNotExist):
        if wants_json:
            return JsonResponse({"ok": False, "message": _("Unknown stage.")}, status=400)
        messages.error(request, _("Unknown stage."))
        return _back(request)

    changed = move_to_stage(startup, stage, user=request.user)
    message = (
        _("%(startup)s moved to %(stage)s.") % {"startup": startup.display_name, "stage": stage.name}
        if changed else _("%(startup)s is already in %(stage)s.") % {"startup": startup.display_name, "stage": stage.name}
    )
    intake_url = None
    registration = pending_intake(startup)
    if changed and registration and (stage.marks_intake_scheduled or stage.marks_intake_done):
        intake_url = reverse("staff:intake_detail", args=[registration.pk])
        message += " " + _("The intake is still open in the intake queue: record it there so the 10-day promise is tracked.")

    if wants_json:
        return JsonResponse({"ok": True, "changed": changed, "stage": stage.pk, "message": message, "intake_url": intake_url})
    if intake_url:
        messages.warning(request, message)
    else:
        messages.success(request, message)
    return _back(request)


def _back(request):
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse("staff:pipeline")
    return redirect(target)
