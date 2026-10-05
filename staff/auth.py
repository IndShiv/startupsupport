"""Sign-in for staff.

* EntraBackend: Microsoft Entra ID (OpenID Connect) with BUas accounts.
* LocalBackend: username/password, for local development only (LOCAL_LOGIN_ENABLED);
  it also supplies group-based permissions, so it stays installed in production.

Who may sign in with Entra ID:
* accounts in the BUas tenant with an allowed email domain, and
* either an app role from Entra ID (ENTRA_ROLE_MAP, synced on every sign-in), or a staff
  account an admin created on the Team page (matched on email the first time).
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import SuspiciousOperation
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from .models import EntraIdentity
from .roles import get_role, link_coach, set_role

logger = logging.getLogger("buss.auth")


class LocalBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not settings.LOCAL_LOGIN_ENABLED:
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)


def claim_email(claims):
    return (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip().lower()


def role_from_claims(claims):
    """Map Entra app roles to a BUSS role; None when the token carries no role information."""
    if not settings.ENTRA_ROLE_MAP or "roles" not in claims:
        return None
    granted = {settings.ENTRA_ROLE_MAP[r] for r in claims.get("roles", []) if r in settings.ENTRA_ROLE_MAP}
    if "Admin" in granted:
        return "Admin"
    if "Coach" in granted:
        return "Coach"
    return ""


class EntraBackend(OIDCAuthenticationBackend):
    def get_user(self, user_id):
        # The library restores sessions without checking is_active; a deactivated account must lose access at once.
        user = super().get_user(user_id)
        return user if user is not None and user.is_active else None

    def get_userinfo(self, access_token, id_token, payload):
        # The verified ID token already holds everything we need (oid, tid, roles, name, email).
        return payload

    def verify_claims(self, claims):
        if claims.get("tid") != settings.ENTRA_TENANT_ID:
            logger.warning("Entra sign-in refused: wrong tenant")
            return False
        email = claim_email(claims)
        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if domain not in settings.ENTRA_ALLOWED_DOMAINS:
            logger.warning("Entra sign-in refused: email domain %s not allowed", domain or "(none)")
            return False
        return bool(claims.get("oid"))

    def filter_users_by_claims(self, claims):
        User = get_user_model()
        identity = EntraIdentity.objects.filter(oid=claims["oid"]).select_related("user").first()
        if identity:
            return User.objects.filter(pk=identity.user_id)
        return User.objects.filter(email__iexact=claim_email(claims))

    def create_user(self, claims):
        role = role_from_claims(claims)
        if not role:
            raise SuspiciousOperation("No BUSS role for this account")
        User = get_user_model()
        email = claim_email(claims)
        user = User.objects.create_user(username=email, email=email, first_name=claims.get("given_name", "")[:150],
                                        last_name=claims.get("family_name", "")[:150])
        user.set_unusable_password()
        user.save()
        self._fill_names(user, claims)
        set_role(user, role)
        EntraIdentity.objects.create(user=user, oid=claims["oid"])
        link_coach(user)
        return user

    def update_user(self, user, claims):
        if not user.is_active:
            raise SuspiciousOperation("Account deactivated")
        EntraIdentity.objects.get_or_create(user=user, defaults={"oid": claims["oid"]})
        role = role_from_claims(claims)
        if role is not None:
            set_role(user, role)  # Entra ID app roles are leading when configured
        if not get_role(user):
            raise SuspiciousOperation("No BUSS role for this account")
        user.email = claim_email(claims)
        self._fill_names(user, claims)
        user.save()
        link_coach(user)
        return user

    @staticmethod
    def _fill_names(user, claims):
        if claims.get("given_name") or claims.get("family_name"):
            user.first_name = claims.get("given_name", user.first_name)[:150]
            user.last_name = claims.get("family_name", user.last_name)[:150]
        elif claims.get("name") and not user.get_full_name():
            first, _, last = claims["name"].partition(" ")
            user.first_name, user.last_name = first[:150], last[:150]
