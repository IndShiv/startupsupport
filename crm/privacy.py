"""GDPR tools: export everything about a student, anonymise or delete them, and find records past retention.

Anonymising keeps the non-identifying facts (domain, study year, dates, stage, coach) so the
statistics stay correct, and removes everything that identifies the student – including the
audit-log history of their records, which holds old values.
"""

from datetime import timedelta

from auditlog.context import disable_auditlog
from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Max, Q
from django.urls import reverse
from django.utils import timezone

from siteconfig.models import AppSettings

from .models import (
    Activity, Founder, FollowUp, GraduationTrack, Notification, OutgoingEmail, PrivacyAction, Registration, Startup,
    Student,
)

ANONYMISED = "[removed]"


def _iso(value):
    return value.isoformat() if value else None


def _log_entries(objects):
    """Audit-log entries of the given model instances."""
    query = Q()
    for obj in objects:
        query |= Q(content_type=ContentType.objects.get_for_model(obj), object_pk=str(obj.pk))
    return LogEntry.objects.filter(query) if query else LogEntry.objects.none()


def related_records(student):
    """Everything that belongs to (or only to) this student, including merged duplicates."""
    students = [student] + list(Student.objects.filter(merged_into=student))
    registrations = list(Registration.objects.filter(student__in=students))
    links = list(Founder.objects.filter(student__in=students).select_related("startup"))
    startups = {link.startup for link in links} | {r.startup for r in registrations}
    sole = [s for s in startups if not s.founder_links.exclude(student__in=students).exists()]
    shared = [s for s in startups if s not in sole]
    return {
        "students": students,
        "registrations": registrations,
        "founder_links": links,
        "sole_startups": sole,
        "shared_startups": shared,
        "graduation_tracks": list(GraduationTrack.objects.filter(student__in=students)),
        "follow_ups": list(FollowUp.objects.filter(student__in=students)) + list(FollowUp.objects.filter(startup__in=sole, student__isnull=True)),
        "activities": list(Activity.objects.filter(startup__in=sole)),
        "emails": list(OutgoingEmail.objects.filter(registration__in=registrations)),
    }


# -- export (right of access / data portability) --------------------------------------------------

def export_student(student, user=None):
    """All personal data held about a student, as a JSON-serialisable dict."""
    r = related_records(student)
    student_ids = [s.pk for s in r["students"]]

    def person(s):
        return {"id": s.pk, "first_name": s.first_name, "last_name": s.last_name, "student_number": s.student_number,
                "email": s.email, "phone": s.phone, "domain": s.domain.name, "study_year": s.study_year.name,
                "created_at": _iso(s.created_at), "archived_at": _iso(s.archived_at)}

    def startup(st):
        others = st.founder_links.exclude(student_id__in=student_ids).count()
        return {"id": st.pk, "name": st.name, "description": st.description, "goals": st.goals, "stage": st.stage.name,
                "coach": st.assigned_coach.full_name if st.assigned_coach else None,
                "paying_customers": st.has_paying_customers, "idea_validated": st.idea_validated,
                "kvk_number": st.kvk_number, "tags": [t.name for t in st.tags.all()],
                "other_founders": others,  # other people's data is not part of this export
                "activity_log": [{"date": _iso(a.date), "type": a.get_kind_display(), "text": a.body,
                                  "by": a.author.get_full_name() if a.author else None}
                                 for a in st.activities.select_related("author").order_by("date")]}

    data = {
        "exported_at": _iso(timezone.now()),
        "controller": "Breda University of Applied Sciences – BUas Startup Support (startupsupport@buas.nl)",
        "student": person(student),
        "merged_duplicate_records": [person(s) for s in r["students"][1:]],
        "registrations": [{
            "id": reg.pk, "submitted_at": _iso(reg.submitted_at), "source": reg.get_source_display(),
            "answers": reg.answers.get("sections") or reg.answers.get("import", {}).get("values"),
            "comments": reg.comments,
            "preferred_coach": reg.preferred_coach.full_name if reg.preferred_coach else None,
            "privacy_consent_at": _iso(reg.consent_at),
            "privacy_statement_version": reg.privacy_statement.version if reg.privacy_statement else None,
            "intake_deadline": _iso(reg.intake_deadline), "intake_scheduled_on": _iso(reg.intake_scheduled_on),
            "intake_held_on": _iso(reg.intake_held_on),
            "intake_coach": reg.intake_coach.full_name if reg.intake_coach else None,
        } for reg in r["registrations"]],
        "startups": [startup(st) for st in r["sole_startups"] + r["shared_startups"]],
        "graduation_tracks": [{"approval": t.get_approval_display(), "topic": t.topic, "supervisor": t.supervisor_name,
                               "hand_in_date": _iso(t.hand_in_date)} for t in r["graduation_tracks"]],
        "follow_ups": [{"title": f.title, "notes": f.notes, "due_date": _iso(f.due_date), "done_at": _iso(f.done_at)}
                       for f in r["follow_ups"]],
        "emails_sent": [{"to": e.to, "subject": e.subject, "status": e.status, "sent_at": _iso(e.sent_at)} for e in r["emails"]],
        "change_history": [{"at": _iso(e.timestamp), "record": f"{e.content_type.model} #{e.object_pk}",
                            "action": e.get_action_display(), "changed_fields": sorted((e.changes_dict or {}).keys()),
                            "by": e.actor.get_full_name() if e.actor else None}
                           for e in _log_entries(r["students"] + r["registrations"] + r["graduation_tracks"]).select_related("actor", "content_type").order_by("timestamp")],
    }
    PrivacyAction.objects.create(action=PrivacyAction.Action.EXPORT, student_ref=student.pk, performed_by=user)
    return data


# -- anonymise / delete ---------------------------------------------------------------------------

def _forget_traces(r):
    """Remove audit-log history and in-app notifications that mention these records."""
    objects = (r["students"] + r["registrations"] + r["graduation_tracks"] + r["founder_links"] + r["follow_ups"]
               + r["activities"] + r["sole_startups"])
    removed = _log_entries(objects).delete()[0]
    urls = [reverse("staff:intake_detail", args=[reg.pk]) for reg in r["registrations"]]
    Notification.objects.filter(url__in=urls).delete()
    return removed


@transaction.atomic
def anonymise_student(student, user=None, reason=""):
    r = related_records(student)
    with disable_auditlog():
        log_entries = _forget_traces(r)
        for s in r["students"]:
            Student.objects.filter(pk=s.pk).update(
                first_name="Anonymised", last_name=f"student #{s.pk}", student_number="", email="", phone="",
                anonymised_at=timezone.now(), archived_at=s.archived_at or timezone.now(),
            )
        for reg in r["registrations"]:
            Registration.objects.filter(pk=reg.pk).update(
                answers={}, comments="", forms_response_id=f"anonymised:{reg.pk}" if reg.forms_response_id else None,
            )
        GraduationTrack.objects.filter(pk__in=[t.pk for t in r["graduation_tracks"]]).update(topic=ANONYMISED, supervisor_name=ANONYMISED)
        FollowUp.objects.filter(pk__in=[f.pk for f in r["follow_ups"]]).delete()
        Activity.objects.filter(pk__in=[a.pk for a in r["activities"]]).update(body=ANONYMISED)
        Startup.objects.filter(pk__in=[s.pk for s in r["sole_startups"]]).update(
            name="", description=ANONYMISED, goals="", kvk_number="", archived_at=timezone.now(),
        )
        for st in r["sole_startups"]:
            st.tags.clear()
        # On startups shared with other founders the student is only removed as founder.
        Founder.objects.filter(student__in=r["students"], startup__in=r["shared_startups"]).delete()
        OutgoingEmail.objects.filter(pk__in=[e.pk for e in r["emails"]]).update(to="", subject=ANONYMISED)
    details = {"registrations": len(r["registrations"]), "startups_anonymised": len(r["sole_startups"]),
               "removed_from_shared_startups": len(r["shared_startups"]), "audit_entries_removed": log_entries}
    PrivacyAction.objects.create(action=PrivacyAction.Action.ANONYMISE, student_ref=student.pk, reason=reason[:200],
                                 details=details, performed_by=user)
    return details


@transaction.atomic
def delete_student(student, user=None, reason=""):
    r = related_records(student)
    with disable_auditlog():
        log_entries = _forget_traces(r)
        OutgoingEmail.objects.filter(pk__in=[e.pk for e in r["emails"]]).delete()
        FollowUp.objects.filter(pk__in=[f.pk for f in r["follow_ups"]]).delete()
        Registration.objects.filter(pk__in=[reg.pk for reg in r["registrations"]]).delete()  # cascades graduation tracks
        Founder.objects.filter(student__in=r["students"]).delete()
        Startup.objects.filter(pk__in=[s.pk for s in r["sole_startups"]]).delete()  # cascades activities
        # Shared startups may still point at a registration of someone else; nothing else references the student.
        Student.objects.filter(pk__in=[s.pk for s in r["students"] if s.pk != student.pk]).delete()
        student_ref = student.pk
        student.delete()
    details = {"registrations": len(r["registrations"]), "startups_deleted": len(r["sole_startups"]),
               "removed_from_shared_startups": len(r["shared_startups"]), "audit_entries_removed": log_entries}
    PrivacyAction.objects.create(action=PrivacyAction.Action.DELETE, student_ref=student_ref, reason=reason[:200],
                                 details=details, performed_by=user)
    return details


# -- retention ----------------------------------------------------------------------------------

def retention_cutoff(now=None):
    years = AppSettings.load().retention_years
    return (now or timezone.now()) - timedelta(days=round(365.25 * years))


def due_for_anonymisation(now=None):
    """Students with no registration, activity or record change within the retention period.

    Covers both inactive students and alumni: once a startup is closed nothing happens any more,
    so its last change ages past the cutoff.
    """
    cutoff = retention_cutoff(now)
    qs = Student.objects.filter(anonymised_at__isnull=True, merged_into__isnull=True).annotate(
        last_registration=Max("registrations__submitted_at"),
        last_activity=Max("startups__last_activity_at"),
        last_change=Max("startups__updated_at"),
    )
    due = []
    for s in qs.select_related("domain"):
        last = max(d for d in (s.last_registration, s.last_activity, s.last_change, s.updated_at) if d)
        if last < cutoff:
            s.last_contact = last
            due.append(s)
    return sorted(due, key=lambda s: s.last_contact)
