"""Admin-only import of historical registrations from a spreadsheet."""

import io
from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from crm import importer
from crm.models import Coach, ImportBatch
from siteconfig.models import Domain, PipelineStage, StudyYear

from .permissions import is_admin, staff_required

MAX_UPLOAD = 5 * 1024 * 1024


def admin_required(view):
    @staff_required
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    return wrapper


def _purge_stale():
    """Uploaded but never imported batches hold personal data: drop them after a day."""
    ImportBatch.objects.filter(status=ImportBatch.Status.UPLOADED, created_at__lt=timezone.now() - timedelta(days=1)).delete()


@admin_required
def import_start(request):
    _purge_stale()
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload or not upload.name.lower().endswith(".xlsx"):
            messages.error(request, _("Please choose an Excel file (.xlsx)."))
        elif upload.size > MAX_UPLOAD:
            messages.error(request, _("The file is larger than 5 MB."))
        else:
            data = upload.read()
            try:
                importer.sheet_names(io.BytesIO(data))
            except Exception:  # noqa: BLE001 - any parse failure means "not a readable workbook"
                messages.error(request, _("This file could not be read as an Excel workbook."))
            else:
                batch = ImportBatch.objects.create(created_by=request.user, filename=upload.name[:200], file_data=data)
                return redirect("staff:import_sheet", pk=batch.pk)
    return render(request, "staff/import_start.html", {"batches": ImportBatch.objects.select_related("created_by")[:20]})


@admin_required
def import_sheet(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, status=ImportBatch.Status.UPLOADED)
    if not batch.file_data:
        return redirect("staff:import_map", pk=pk)
    names = importer.sheet_names(io.BytesIO(bytes(batch.file_data)))
    if request.method == "POST" and request.POST.get("sheet") in names:
        try:
            header, rows = importer.parse_sheet(io.BytesIO(bytes(batch.file_data)), request.POST["sheet"])
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            batch.sheet, batch.header, batch.rows = request.POST["sheet"], header, rows
            batch.mapping = importer.default_mapping(header, rows, batch.sheet)
            batch.file_data = None  # keep only the chosen sheet
            batch.save()
            return redirect("staff:import_map", pk=pk)
    return render(request, "staff/import_sheet.html", {"batch": batch, "names": names})


def _int_or_none(value, limit):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value < limit else None


@admin_required
def import_map(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, status=ImportBatch.Status.UPLOADED)
    if not batch.sheet:
        return redirect("staff:import_sheet", pk=pk)
    m = batch.mapping
    if request.method == "POST":
        old_columns = dict(m["columns"])
        m["columns"] = {t: _int_or_none(request.POST.get(f"col_{t}"), len(batch.header)) for t in importer.TARGETS}
        try:
            m["default_date"] = date.fromisoformat(request.POST.get("default_date", "")).isoformat()
        except ValueError:
            messages.error(request, _("Please enter a valid default registration date."))
        for i, value in enumerate(m["programs"]):
            m["programs"][value] = {"domain": request.POST.get(f"program_domain_{i}", importer.UNKNOWN_DOMAIN),
                                    "year": request.POST.get(f"program_year_{i}", "")}
        for i, value in enumerate(m["coaches"]):
            m["coaches"][value] = request.POST.get(f"coach_{i}", "")
        for i, value in enumerate(m["goc"]):
            m["goc"][value] = request.POST.get(f"goc_{i}", "unknown")
        for i, key in enumerate(m["colours"]):
            m["colours"][key]["stage"] = request.POST.get(f"colour_stage_{i}", "Coaching")
            m["colours"][key]["tag"] = request.POST.get(f"colour_tag_{i}", "").strip()[:50]
        # A different column was chosen: rebuild that value list with fresh guesses.
        guesses = {
            "programs": lambda v: dict(zip(("domain", "year"), importer.guess_program(v))),
            "coaches": importer.guess_coach,
            "goc": importer.guess_yes_no,
        }
        for target, key in (("program", "programs"), ("coach", "coaches"), ("goc", "goc")):
            if m["columns"].get(target) != old_columns.get(target):
                m[key] = {v: guesses[key](v) for v in importer.distinct(batch.rows, m["columns"].get(target))}
        batch.mapping = m
        batch.save(update_fields=["mapping"])
        if request.POST.get("next") == "preview":
            return redirect("staff:import_preview", pk=pk)
        messages.success(request, _("Mapping updated."))
        return redirect("staff:import_map", pk=pk)

    columns = [{"target": t, "label": label, "selected": m["columns"].get(t)} for t, (label, _w) in importer.TARGETS.items()]

    def with_counts(key, target):
        counts = importer.distinct(batch.rows, m["columns"].get(target))
        return [(i, value, choice, counts.get(value, 0)) for i, (value, choice) in enumerate(m[key].items())]

    return render(request, "staff/import_map.html", {
        "batch": batch, "columns": columns, "header": list(enumerate(batch.header)),
        "programs": with_counts("programs", "program"),
        "coach_values": with_counts("coaches", "coach"),
        "goc_values": with_counts("goc", "goc"),
        "colours": [(i, key, c) for i, (key, c) in enumerate(m["colours"].items())],
        "domains": [d.name for d in Domain.objects.order_by("order")] + [importer.UNKNOWN_DOMAIN],
        "years": [y.name for y in StudyYear.objects.order_by("order")],
        "coaches": Coach.objects.all(),
        "stages": PipelineStage.objects.order_by("order"),
        "unknown_domain": importer.UNKNOWN_DOMAIN,
    })


@admin_required
def import_preview(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, status=ImportBatch.Status.UPLOADED)
    plan = importer.build_plan(batch)
    counts = {a: sum(1 for p in plan if p.action == a) for a in ("new", "link", "skip", "error")}
    return render(request, "staff/import_preview.html", {
        "batch": batch, "plan": plan, "counts": counts,
        "to_import": counts["new"] + counts["link"],
        "people": sum(len(p.people) for p in plan if p.action in ("new", "link")),
    })


@admin_required
@require_POST
def import_run(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, status=ImportBatch.Status.UPLOADED)
    counts = importer.run_import(batch, request.user)
    messages.success(request, _("Import finished: %(n)d registrations imported, %(s)d new students.") % {
        "n": counts["new"] + counts["link"], "s": counts["students_created"]})
    return redirect("staff:import_start")


@admin_required
@require_POST
def import_discard(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, status=ImportBatch.Status.UPLOADED)
    batch.delete()
    messages.success(request, _("Upload discarded; nothing was imported."))
    return redirect("staff:import_start")
