from .permissions import is_admin, is_staff_member


def staff_nav(request):
    user = getattr(request, "user", None)
    if not (user and is_staff_member(user)):
        return {}
    return {
        "is_admin": is_admin(user),
        "unread_notifications": user.notifications.filter(read_at__isnull=True).count,
    }
