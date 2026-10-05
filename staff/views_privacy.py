"""GDPR tools for admins: export a student's data, anonymise or delete, retention overview."""

import json

from django.contrib import messages
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from crm import privacy
from crm.models import PrivacyAction, Registration, Student
from siteconfig.models import AppSettings

from .views_import import admin_required


@admin_required
def privacy_overview(request):
    settings = AppSettings.load()
    return render(request, "staff/privacy.html", {
        "due": privacy.due_for_anonymisation(),
        "cutoff": privacy.retention_cutoff(),
        "retention_years": settings.retention_years,
        "actions": PrivacyAction.objects.select_related("performed_by")[:30],
        "without_consent": Registration.objects.filter(consent_at__isnull=True, student__anonymised_at__isnull=True).count(),
    })


@admin_required
@require_POST
def privacy_bulk_anonymise(request):
    ids = [int(i) for i in request.POST.getlist("student") if i.isdigit()]
    due_ids = {s.pk for s in privacy.due_for_anonymisation()}
    done = 0
    for student in Student.objects.filter(pk__in=[i for i in ids if i in due_ids]):
        privacy.anonymise_student(student, request.user, reason="Retention period passed")
        done += 1
    messages.success(request, _("%(n)d student record(s) anonymised.") % {"n": done})
    return redirect("staff:privacy")


@admin_required
def student_data_export(request, pk):
    student = get_object_or_404(Student, pk=pk)
    data = privacy.export_student(student, request.user)
    response = HttpResponse(json.dumps(data, indent=2, ensure_ascii=False), content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="buss-student-{student.pk}-{timezone.localdate():%Y-%m-%d}.json"'
    response["Cache-Control"] = "no-store"
    return response


def _confirm(request, pk, action):
    student = get_object_or_404(Student.objects.current(), pk=pk)
    records = privacy.related_records(student)
    error = None
    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        if not request.POST.get("confirm"):
            error = _("Please tick the box to confirm.")
        elif not reason:
            error = _("Please give a reason (without personal data).")
        else:
            try:
                if action == "anonymise":
                    privacy.anonymise_student(student, request.user, reason=reason)
                    messages.success(request, _("The student has been anonymised."))
                    return redirect("staff:student_detail", pk=pk)
                privacy.delete_student(student, request.user, reason=reason)
                messages.success(request, _("The student and their records have been deleted."))
                return redirect("staff:privacy")
            except ProtectedError:
                error = _("This student cannot be deleted because other records still refer to their startup. Anonymise instead.")
    return render(request, "staff/privacy_confirm.html", {"s": student, "r": records, "action": action, "error": error})


@admin_required
def student_anonymise(request, pk):
    return _confirm(request, pk, "anonymise")


@admin_required
def student_delete(request, pk):
    return _confirm(request, pk, "delete")
