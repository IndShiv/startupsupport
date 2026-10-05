"""Staff roles. A role is a Django group; both roles may use the configuration admin (is_staff)."""

from django.contrib.auth.models import Group

from .permissions import ADMIN_GROUP, COACH_GROUP

ROLES = [(ADMIN_GROUP, "Admin"), (COACH_GROUP, "Coach")]
ROLE_NAMES = [name for name, _ in ROLES]


def get_role(user):
    names = set(user.groups.filter(name__in=ROLE_NAMES).values_list("name", flat=True))
    if ADMIN_GROUP in names or user.is_superuser:
        return ADMIN_GROUP
    if COACH_GROUP in names:
        return COACH_GROUP
    return ""


def set_role(user, role):
    """Give the user exactly one role ("" removes access)."""
    user.groups.remove(*Group.objects.filter(name__in=ROLE_NAMES))
    if role:
        user.groups.add(Group.objects.get(name=role))
    user.is_staff = bool(role) or user.is_superuser
    user.save(update_fields=["is_staff"])
    if hasattr(user, "_buss_groups"):
        del user._buss_groups


def link_coach(user):
    """Connect the user to the coach profile with the same email address, if it has no login yet."""
    from crm.models import Coach

    if not user.email or hasattr(user, "coach"):
        return None
    coach = Coach.objects.filter(email__iexact=user.email, user__isnull=True).first()
    if coach:
        coach.user = user
        coach.save(update_fields=["user"])
    return coach
