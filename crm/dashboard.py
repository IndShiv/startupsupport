"""Figures for the staff dashboard. Pure queries, kept out of the view so they can be tested."""

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count, F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from siteconfig.models import AppSettings, Domain, PipelineStage

from .intake import coaches_with_caseload
from .models import GraduationTrack, Registration, Startup

PERIODS = {
    "3m": _("Last 3 months"),
    "6m": _("Last 6 months"),
    "12m": _("Last 12 months"),
    "ay": _("This academic year"),
    "all": _("All time"),
}
DEFAULT_PERIOD = "12m"
HAND_IN_WINDOW_WEEKS = 8
INACTIVE_SHOWN = 10


@dataclass
class Period:
    key: str
    label: str
    start: date  # first day of the first month shown (inclusive)
    end: date  # today

    @property
    def length_days(self):
        return (self.end - self.start).days + 1


def _month_start(day, months_back=0):
    year, month = day.year, day.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def get_period(key, today=None):
    today = today or timezone.localdate()
    key = key if key in PERIODS else DEFAULT_PERIOD
    if key == "all":
        first = Registration.objects.order_by("submitted_at").values_list("submitted_at", flat=True).first()
        start = _month_start(timezone.localdate(first)) if first else _month_start(today)
    elif key == "ay":
        # The Dutch academic year starts on 1 September.
        start = date(today.year if today.month >= 9 else today.year - 1, 9, 1)
    else:
        start = _month_start(today, int(key[:-1]) - 1)
    return Period(key, PERIODS[key], start, today)


def _in_period(period):
    return Registration.objects.filter(submitted_at__date__gte=period.start, submitted_at__date__lte=period.end)


def _next_month(day):
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


def months(period):
    result, current = [], period.start
    while current <= period.end:
        result.append(current)
        current = _next_month(current)
    return result


def turnaround(registrations, today):
    """Share of registrations whose intake was arranged within the promised working days.

    Counted: registrations that were scheduled, plus those still waiting whose deadline
    has passed (they are late). Registrations still within their deadline are not counted yet.
    """
    decided = registrations.filter(Q(intake_scheduled_on__isnull=False) | Q(intake_deadline__lt=today))
    total = decided.count()
    on_time = decided.filter(intake_scheduled_on__isnull=False, intake_scheduled_on__lte=F("intake_deadline")).count()
    return {"total": total, "on_time": on_time, "late": total - on_time, "pct": round(100 * on_time / total) if total else None}


def registrations_per_month(period):
    """One row per month: registrations, and the intake turnaround of that month's registrations."""
    result = []
    for month in months(period):
        month_regs = Registration.objects.filter(submitted_at__date__gte=month, submitted_at__date__lt=_next_month(month))
        result.append({"month": month, "count": month_regs.count(), "turnaround": turnaround(month_regs, period.end)})
    return _bars(result)


def kpis(period):
    today = period.end
    settings = AppSettings.load()
    regs = _in_period(period)
    previous_start = period.start - timedelta(days=period.length_days)
    previous = Registration.objects.filter(submitted_at__date__gte=previous_start, submitted_at__date__lt=period.start).count()
    waiting = Registration.objects.awaiting_intake()
    return {
        "registrations": regs.count(),
        "registrations_previous": previous if period.key != "all" else None,
        "waiting": waiting.count(),
        "overdue": waiting.filter(intake_deadline__lt=today).count(),
        "turnaround": turnaround(regs, today),
        "intake_days": settings.intake_working_days,
        "active_startups": Startup.objects.active().count(),
        "returning": regs.filter(is_duplicate_student=True).count(),
    }


def _bars(items, key="count"):
    """Add each item's share of the largest value (for bar widths)."""
    top = max((i[key] for i in items), default=0)
    for item in items:
        item["pct_of_max"] = round(100 * item[key] / top, 1) if top else 0
    return items


def per_stage():
    rows = PipelineStage.objects.annotate(
        count=Count("startups", filter=Q(startups__archived_at__isnull=True))
    ).filter(Q(active=True) | Q(count__gt=0)).order_by("order")
    return _bars([{"label": s.name, "count": s.count, "closed": s.is_closed, "pk": s.pk} for s in rows])


def per_domain(period):
    rows = Domain.objects.annotate(
        count=Count("students__registrations", filter=Q(
            students__registrations__submitted_at__date__gte=period.start,
            students__registrations__submitted_at__date__lte=period.end,
        ))
    ).order_by("order")
    return _bars([{"label": d.name, "count": d.count, "pk": d.pk} for d in rows if d.active or d.count])


def caseload():
    rows = sorted(coaches_with_caseload(), key=lambda c: (-c.active_caseload, c.first_name))
    return _bars([{"label": c.full_name, "count": c.active_caseload, "pk": c.pk} for c in rows])


def graduation(today):
    tracks = GraduationTrack.objects.select_related("student", "startup__assigned_coach").filter(
        student__anonymised_at__isnull=True, startup__archived_at__isnull=True, startup__stage__is_closed=False,
    )
    window_end = today + timedelta(weeks=HAND_IN_WINDOW_WEEKS)
    return {
        "approval_missing": list(tracks.filter(approval=GraduationTrack.Approval.NOT_YET).order_by("hand_in_date")),
        "upcoming": list(tracks.filter(hand_in_date__gte=today, hand_in_date__lte=window_end).order_by("hand_in_date")),
        "overdue_hand_in": list(tracks.filter(hand_in_date__lt=today).order_by("hand_in_date")),
        "window_weeks": HAND_IN_WINDOW_WEEKS,
    }


def inactive_startups(now=None):
    now = now or timezone.now()
    weeks = AppSettings.load().inactivity_weeks
    cutoff = now - timedelta(weeks=weeks)
    qs = Startup.objects.active().select_related("assigned_coach", "stage").filter(
        Q(last_activity_at__lt=cutoff) | Q(last_activity_at__isnull=True, created_at__lt=cutoff)
    ).order_by("last_activity_at", "created_at")
    # Longest-quiet first; the dashboard shows the top of the list and links to the full filtered list.
    return {"weeks": weeks, "count": qs.count(), "startups": list(qs.prefetch_related("founders")[:INACTIVE_SHOWN])}
