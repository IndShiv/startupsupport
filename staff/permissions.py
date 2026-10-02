"""Who may use the staff application. Roles are Django groups: 'Admin' and 'Coach'."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

ADMIN_GROUP = "Admin"
COACH_GROUP = "Coach"


def _groups(user):
    if not hasattr(user, "_buss_groups"):
        user._buss_groups = set(user.groups.values_list("name", flat=True))
    return user._buss_groups


def is_admin(user):
    return user.is_authenticated and user.is_active and (user.is_superuser or ADMIN_GROUP in _groups(user))


def is_staff_member(user):
    return is_admin(user) or (user.is_authenticated and user.is_active and COACH_GROUP in _groups(user))


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_staff_member(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
