"""The intake promise: every registration gets an intake within N working days.

The clock stops when the intake is *scheduled*; the date it was *held* and the
coach who held it are recorded separately.
"""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from siteconfig.models import AppSettings, PipelineStage

from .models import Activity, Coach, Registration
from .workdays import add_working_days, working_days_between


@dataclass
class Urgency:
    days_left: int  # working days; 0 = due today, negative = overdue
    level: str  # "overdue", "due-soon" or "ok"

    @property
    def label(self):
        if self.days_left < 0:
            n = -self.days_left
            return ngettext("%(n)d working day overdue", "%(n)d working days overdue", n) % {"n": n}
        if self.days_left == 0:
            return _("Due today")
        return ngettext("%(n)d working day left", "%(n)d working days left", self.days_left) % {"n": self.days_left}


def urgency(registration, today=None, due_soon=None):
    today = today or timezone.localdate()
    if due_soon is None:
        due_soon = AppSettings.load().intake_due_soon_days
    days = working_days_between(today, registration.intake_deadline)
    level = "overdue" if days < 0 else "due-soon" if days <= due_soon else "ok"
    return Urgency(days, level)


def coaches_with_caseload():
    """Active coaches annotated with `active_caseload` (startups not archived and not in a closed stage)."""
    return Coach.objects.filter(active=True).prefetch_related("domains").annotate(
        active_caseload=Count("startups", filter=Q(startups__archived_at__isnull=True, startups__stage__is_closed=False))
    )


def conflicting_students(students, coach):
    """Graduation-track students whose own domain is one of the coach's home domains."""
    if coach is None:
        return []
    coach_domains = {d.pk for d in coach.domains.all()}
    return [s for s in students if s.on_graduation_track and s.domain_id in coach_domains]


def domain_conflict(registration, coach):
    """Graduation-track students must get a coach from a different domain than their own."""
    return bool(conflicting_students([registration.student], coach))


def advance_stage(startup, *, scheduled=False, done=False):
    """Move the startup forward to the 'intake scheduled'/'intake done' stage, never backwards."""
    flag = "marks_intake_done" if done else "marks_intake_scheduled" if scheduled else None
    if not flag:
        return
    target = PipelineStage.objects.filter(**{flag: True}).order_by("order").first()
    if target and target.order > startup.stage.order:
        startup.stage = target


@transaction.atomic
def schedule_intake(registration, *, scheduled_on, planned_at=None, coach=None, assign_coach=False, user=None):
    registration.intake_scheduled_on = scheduled_on
    registration.intake_planned_at = planned_at
    registration.intake_coach = coach
    registration.save(update_fields=["intake_scheduled_on", "intake_planned_at", "intake_coach"])
    startup = registration.startup
    if assign_coach and coach:
        startup.assigned_coach = coach
    advance_stage(startup, scheduled=True)
    startup.save()


@transaction.atomic
def record_intake_held(registration, *, held_on, coach, assign_coach=None, note="", user=None):
    if registration.intake_scheduled_on is None:
        registration.intake_scheduled_on = held_on  # held without separate scheduling: clock stops on that day
    registration.intake_held_on = held_on
    registration.intake_coach = coach
    registration.save(update_fields=["intake_scheduled_on", "intake_held_on", "intake_coach"])
    startup = registration.startup
    if assign_coach:
        startup.assigned_coach = assign_coach
    advance_stage(startup, done=True)
    startup.save()
    Activity.objects.create(
        startup=startup,
        kind=Activity.Kind.INTAKE,
        date=held_on,
        author=user,
        body=note or f"Intake held by {coach.full_name}.",
    )


def recompute_open_deadlines():
    """Recalculate deadlines of registrations still waiting, e.g. after closure days change."""
    days = AppSettings.load().intake_working_days
    updated = 0
    for registration in Registration.objects.awaiting_intake().only("pk", "submitted_at", "intake_deadline"):
        deadline = add_working_days(timezone.localdate(registration.submitted_at), days)
        if deadline != registration.intake_deadline:
            Registration.objects.filter(pk=registration.pk).update(intake_deadline=deadline)
            updated += 1
    return updated


@transaction.atomic
def move_to_stage(startup, stage, *, user=None):
    """Move a startup to another pipeline stage and note it in the activity log. Returns True if it changed."""
    if startup.stage_id == stage.pk:
        return False
    old = startup.stage
    startup.stage = stage
    startup.save(update_fields=["stage", "updated_at"])
    Activity.objects.create(
        startup=startup, kind=Activity.Kind.STAGE, date=timezone.localdate(), author=user,
        body=f"Moved from “{old.name}” to “{stage.name}”.",
    )
    return True


def pending_intake(startup):
    """The startup's most recent registration that still has no intake scheduled, if any."""
    return startup.registrations.filter(intake_scheduled_on__isnull=True, intake_held_on__isnull=True).order_by("-submitted_at").first()
