from django.shortcuts import render
from django.utils import timezone

from crm import dashboard

from .permissions import staff_required


@staff_required
def dashboard_view(request):
    period = dashboard.get_period(request.GET.get("period", dashboard.DEFAULT_PERIOD))
    today = timezone.localdate()
    monthly = dashboard.registrations_per_month(period)
    counts = [m["count"] for m in monthly]
    peak = max(counts) if counts else 0
    for m in monthly:
        # Label only the peak and the latest month on the chart; the rest is in tooltips and the table.
        m["labelled"] = m["count"] and (m["count"] == peak or m is monthly[-1])
    k = dashboard.kpis(period)
    pct = k["turnaround"]["pct"]
    k["turnaround_level"] = None if pct is None else "good" if pct >= 90 else "warning" if pct >= 75 else "critical"
    return render(request, "staff/dashboard.html", {
        "period": period,
        "periods": dashboard.PERIODS,
        "kpi": k,
        "monthly": monthly,
        "stages": dashboard.per_stage(),
        "domains": dashboard.per_domain(period),
        "caseload": dashboard.caseload(),
        "graduation": dashboard.graduation(today),
        "inactive": dashboard.inactive_startups(),
        "today": today,
    })
