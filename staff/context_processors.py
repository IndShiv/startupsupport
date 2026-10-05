from datetime import timedelta

from django.utils import timezone

from crm.models import FollowUp

from .permissions import is_admin, is_staff_member


def end_of_week(day=None):
    day = day or timezone.localdate()
    return day + timedelta(days=6 - day.weekday())


def staff_nav(request):
    user = getattr(request, "user", None)
    if not (user and is_staff_member(user)):
        return {}
    return {
        "is_admin": is_admin(user),
        "unread_notifications": user.notifications.filter(read_at__isnull=True).count,
        # Overdue plus due this week, for the menu badge (evaluated only when the template uses it).
        "my_followups_due": lambda: FollowUp.objects.open().for_user(user).due_by(end_of_week()).count(),
    }
