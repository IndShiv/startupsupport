"""Export the filtered student and startup lists as CSV or Excel."""

from django.http import Http404, HttpResponse
from django.utils import timezone

from crm import exports
from crm.filters import StartupFilterForm, StudentFilterForm
from crm.models import ExportLog

from .permissions import staff_required

LISTS = {
    "students": (StudentFilterForm, exports.prepare_students, exports.STUDENT_COLUMNS, "Students"),
    "startups": (StartupFilterForm, exports.prepare_startups, exports.STARTUP_COLUMNS, "Startups"),
}
CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _describe_filters(form):
    """Human-readable filters for the 'About this export' sheet and the export log."""
    if not form.is_valid():
        return {}
    described = {}
    for name, value in form.cleaned_data.items():
        if value in (None, "", False) or (hasattr(value, "exists") and not value.exists()):
            continue
        label = str(form.fields[name].label)
        if hasattr(value, "__iter__") and not isinstance(value, str):
            value = ", ".join(str(v) for v in value)
        elif name in ("scope", "status", "graduation", "paying", "validated"):
            value = str(dict(form.fields[name].choices).get(value, value))
        described[label] = str(value) if value is not True else "Yes"
    return described


@staff_required
def export_list(request, kind, file_format):
    if kind not in LISTS or file_format not in CONTENT_TYPES:
        raise Http404
    form_class, prepare, columns, title = LISTS[kind]
    form = form_class(request.GET, coach=getattr(request.user, "coach", None))
    objects = list(prepare(form.filter()))
    filters = _describe_filters(form)
    now = timezone.localtime()

    if file_format == "csv":
        content = exports.to_csv(objects, columns)
    else:
        who = request.user.get_full_name() or request.user.username
        about = [("List", title), ("Exported by", who), ("Exported at", now.replace(tzinfo=None))]
        about += [(f"Filter: {label}", value) for label, value in filters.items()]
        content, _count = exports.to_xlsx(objects, columns, title=title, about=about)

    ExportLog.objects.create(user=request.user, kind=kind, file_format=file_format, filters=filters, row_count=len(objects))
    response = HttpResponse(content, content_type=CONTENT_TYPES[file_format])
    response["Content-Disposition"] = f'attachment; filename="buss-{kind}-{now:%Y-%m-%d}.{file_format}"'
    response["Cache-Control"] = "no-store"  # personal data: don't keep copies in browser/proxy caches
    return response
