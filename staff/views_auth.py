"""Sign-in and sign-out pages."""

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.dispatch import receiver
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

logger = logging.getLogger("buss.auth")


class StaffLoginView(LoginView):
    template_name = "staff/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if not settings.LOCAL_LOGIN_ENABLED:
            raise PermissionDenied("Password sign-in is disabled; use your BUas account.")
        return super().post(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        if request.GET.get("sso") == "failed":
            messages.error(request, _(
                "Signing in with your BUas account did not work. Your account may not have access to BUSS yet: "
                "please ask a BUSS admin to add you."
            ))
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sso_enabled"] = settings.SSO_ENABLED
        context["local_login_enabled"] = settings.LOCAL_LOGIN_ENABLED
        return context


@require_POST
def staff_logout(request):
    via_sso = request.session.get("login_method") == "sso"
    logout(request)
    if via_sso and settings.SSO_ENABLED:
        # Also end the Microsoft session, then come back to our sign-in page.
        back = settings.SITE_URL + reverse("staff:login")
        return redirect(f"{settings.ENTRA_LOGOUT_URL}?{urlencode({'post_logout_redirect_uri': back})}")
    return redirect("staff:login")


def admin_login_redirect(request, extra_context=None):
    """The configuration admin uses the same sign-in as the staff app (BUas account)."""
    target = reverse("staff:login")
    next_url = request.GET.get("next")
    if next_url:
        target += "?" + urlencode({"next": next_url})
    return redirect(target)


@receiver(user_logged_in)
def _remember_login_method(sender, request, user, **kwargs):
    method = "sso" if getattr(user, "backend", "").endswith("EntraBackend") else "password"
    if request is not None:
        request.session["login_method"] = method
    logger.info("Staff sign-in: user=%s method=%s", user.pk, method)


@receiver(user_login_failed)
def _log_failed_login(sender, credentials, request=None, **kwargs):
    logger.warning("Failed staff sign-in attempt (password)")
