"""Staff sign-in (Entra ID and local), roles, the Team page and the permission matrix."""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import SuspiciousOperation
from django.test import RequestFactory, override_settings

from crm.models import Coach
from staff.auth import EntraBackend, LocalBackend
from staff.models import EntraIdentity
from staff.roles import get_role, set_role

pytestmark = pytest.mark.django_db
User = get_user_model()
TENANT = "11111111-2222-3333-4444-555555555555"
_MS = f"https://login.microsoftonline.com/{TENANT}"
ENTRA = dict(ENTRA_TENANT_ID=TENANT, ENTRA_CLIENT_ID="client", OIDC_RP_CLIENT_ID="client", SSO_ENABLED=True,
             ENTRA_ROLE_MAP={"BUSS.Admin": "Admin", "BUSS.Coach": "Coach"}, ENTRA_ALLOWED_DOMAINS=["buas.nl"],
             # settings.py derives these from the tenant at start-up, so override them too
             OIDC_OP_AUTHORIZATION_ENDPOINT=f"{_MS}/oauth2/v2.0/authorize", ENTRA_LOGOUT_URL=f"{_MS}/oauth2/v2.0/logout")


def claims(**overrides):
    data = {"tid": TENANT, "oid": "oid-1", "preferred_username": "Roeland.Bottema@buas.nl",
            "given_name": "Roeland", "family_name": "Bottema", "name": "Roeland Bottema", "roles": ["BUSS.Coach"]}
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def sign_in(c):
    backend = EntraBackend()
    if not backend.verify_claims(c):
        raise SuspiciousOperation("claims")
    users = backend.filter_users_by_claims(c)
    return backend.update_user(users[0], c) if users else backend.create_user(c)


# -- Entra ID backend ------------------------------------------------------------------------------

@override_settings(**ENTRA)
@pytest.mark.parametrize("change, ok", [
    ({}, True),
    ({"tid": "other-tenant"}, False),
    ({"preferred_username": "someone@gmail.com"}, False),
    ({"preferred_username": None}, False),
    ({"oid": None}, False),
])
def test_verify_claims(reference, change, ok):
    assert EntraBackend().verify_claims(claims(**change)) is ok


@override_settings(**ENTRA)
def test_first_sign_in_with_app_role_creates_coach(reference):
    Coach.objects.filter(first_name="Roeland").update(email="roeland.bottema@buas.nl")
    user = sign_in(claims())
    assert user.email == "roeland.bottema@buas.nl" and user.get_full_name() == "Roeland Bottema"
    assert get_role(user) == "Coach" and user.is_staff and not user.has_usable_password()
    assert user.entra.oid == "oid-1"
    assert user.coach.first_name == "Roeland"  # linked to the coach card by email


@override_settings(**ENTRA)
def test_admin_app_role(reference):
    assert get_role(sign_in(claims(roles=["BUSS.Coach", "BUSS.Admin"]))) == "Admin"


@override_settings(**ENTRA)
def test_no_role_and_not_added_is_refused(reference):
    with pytest.raises(SuspiciousOperation):
        sign_in(claims(roles=[]))
    with pytest.raises(SuspiciousOperation):
        sign_in(claims(roles=None))
    assert not User.objects.exists()


@override_settings(**ENTRA)
def test_pre_added_team_member_signs_in_without_app_roles(reference):
    user = User.objects.create_user("roeland.bottema@buas.nl", "roeland.bottema@buas.nl")
    set_role(user, "Coach")
    signed_in = sign_in(claims(roles=None))
    assert signed_in == user and EntraIdentity.objects.get().user == user


@override_settings(**ENTRA)
def test_later_sign_in_matches_on_object_id_even_if_email_changes(reference):
    user = sign_in(claims())
    again = sign_in(claims(preferred_username="r.bottema@buas.nl"))
    assert again == user and again.email == "r.bottema@buas.nl"
    assert User.objects.count() == 1


@override_settings(**ENTRA)
def test_app_roles_are_synced_on_every_sign_in(reference):
    user = sign_in(claims(roles=["BUSS.Admin"]))
    assert get_role(user) == "Admin"
    assert get_role(sign_in(claims(roles=["BUSS.Coach"]))) == "Coach"
    with pytest.raises(SuspiciousOperation):  # role removed in Entra ID: no access any more
        sign_in(claims(roles=[]))
    user.refresh_from_db()
    assert get_role(user) == "" and not user.is_staff


@override_settings(**ENTRA)
def test_deactivated_user_is_refused(reference):
    user = sign_in(claims())
    User.objects.filter(pk=user.pk).update(is_active=False)
    with pytest.raises(SuspiciousOperation):
        sign_in(claims())


@override_settings(**dict(ENTRA, ENTRA_ROLE_MAP={}))
def test_without_role_map_roles_come_from_the_team_page(reference):
    user = User.objects.create_user("roeland.bottema@buas.nl", "roeland.bottema@buas.nl")
    set_role(user, "Admin")
    assert get_role(sign_in(claims(roles=["BUSS.Coach"]))) == "Admin"  # app roles ignored


@override_settings(**ENTRA)
def test_full_callback_flow(reference, client):
    """authenticate() with the token exchange and signature check simulated."""
    request = RequestFactory().get("/oidc/callback/", {"code": "abc", "state": "xyz"})
    SessionMiddleware(lambda r: None).process_request(request)
    backend = EntraBackend()
    with mock.patch.object(EntraBackend, "get_token", return_value={"id_token": "t", "access_token": "a"}), \
         mock.patch.object(EntraBackend, "verify_token", return_value=claims()):
        user = backend.authenticate(request, nonce="n", code_verifier="v")
    assert user is not None and get_role(user) == "Coach"
    with mock.patch.object(EntraBackend, "get_token", return_value={"id_token": "t", "access_token": "a"}), \
         mock.patch.object(EntraBackend, "verify_token", return_value=claims(tid="evil")):
        assert backend.authenticate(request, nonce="n") is None


# -- local sign-in, login page, logout ------------------------------------------------------------------

def test_local_login_works_when_enabled(client, make_user):
    make_user("coachy", "Coach")
    assert client.post("/staff/login/", {"username": "coachy", "password": "pw"}).status_code == 302


@override_settings(LOCAL_LOGIN_ENABLED=False)
def test_local_login_disabled_in_production(client, make_user):
    make_user("coachy", "Coach")
    assert LocalBackend().authenticate(None, username="coachy", password="pw") is None
    assert client.post("/staff/login/", {"username": "coachy", "password": "pw"}).status_code == 403
    assert 'name="password"' not in client.get("/staff/login/").content.decode()


@override_settings(**ENTRA)
def test_login_page_offers_buas_sign_in(client, reference):
    content = client.get("/staff/login/?next=/staff/pipeline/").content.decode()
    assert "Sign in with your BUas account" in content
    assert "/oidc/authenticate/?next=/staff/pipeline/" in content


@override_settings(**ENTRA)
def test_sign_in_redirects_to_microsoft_with_pkce(client, reference):
    response = client.get("/oidc/authenticate/")
    assert response.url.startswith(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize")
    assert "code_challenge=" in response.url and "scope=openid+email+profile" in response.url


def test_failed_sso_shows_explanation(client, reference):
    assert "ask a BUSS admin to add you" in client.get("/staff/login/?sso=failed").content.decode()


@override_settings(**ENTRA)
def test_logout_after_sso_also_signs_out_of_microsoft(client, make_user):
    user = make_user("coachy", "Coach")
    client.force_login(user)
    session = client.session
    session["login_method"] = "sso"
    session.save()
    response = client.post("/staff/logout/")
    assert response.url.startswith(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/logout?post_logout_redirect_uri=")
    assert client.get("/staff/dashboard/").status_code == 302


def test_password_logout_returns_to_login(client, make_user):
    client.force_login(make_user("coachy", "Coach"))
    assert client.post("/staff/logout/").url == "/staff/login/"
    assert client.get("/staff/logout/").status_code == 405


def test_admin_login_uses_staff_sign_in(client, reference):
    response = client.get("/admin/login/?next=/admin/")
    assert response.url == "/staff/login/?next=%2Fadmin%2F"


# -- Team page --------------------------------------------------------------------------------------------

@pytest.fixture
def boss(make_user):
    return make_user("boss", "Admin")


def test_team_is_admin_only(client, make_user, boss):
    client.force_login(make_user("coachy", "Coach"))
    assert client.get("/staff/team/").status_code == 403
    client.force_login(boss)
    assert client.get("/staff/team/").status_code == 200


def test_add_team_member(client, boss):
    client.force_login(boss)
    tijs = Coach.objects.get(first_name="Tijs")
    response = client.post("/staff/team/add/", {"email": "T.vanEs@buas.nl", "first_name": "Tijs", "last_name": "van Es",
                                                "role": "Coach", "coach": tijs.pk, "active": "on"})
    assert response.status_code == 302
    user = User.objects.get(email="t.vanes@buas.nl")
    assert get_role(user) == "Coach" and user.is_staff and not user.has_usable_password()
    tijs.refresh_from_db()
    assert tijs.user == user


def test_change_role_and_remove_access(client, boss, make_user):
    member = make_user("member", "Coach")
    client.force_login(boss)
    data = {"email": "member@buas.nl", "first_name": "M", "last_name": "B", "role": "Admin", "active": "on"}
    client.post(f"/staff/team/{member.pk}/", data)
    assert get_role(member) == "Admin"
    client.post(f"/staff/team/{member.pk}/", dict(data, role=""))
    member.refresh_from_db()
    assert get_role(member) == "" and not member.is_staff


def test_admin_cannot_lock_themselves_out(client, boss):
    client.force_login(boss)
    response = client.post(f"/staff/team/{boss.pk}/", {"email": "boss@buas.nl", "first_name": "B", "last_name": "A", "role": "Coach", "active": "on"})
    assert response.status_code == 200 and "your own admin role" in response.content.decode()
    assert get_role(boss) == "Admin"


def test_duplicate_email_refused(client, boss, make_user):
    make_user("existing").__class__.objects.filter(username="existing").update(email="x@buas.nl")
    client.force_login(boss)
    response = client.post("/staff/team/add/", {"email": "X@buas.nl", "first_name": "X", "last_name": "Y", "role": "Coach", "active": "on"})
    assert "already a login" in response.content.decode()


# -- permission matrix -------------------------------------------------------------------------------------

STAFF_PAGES = ["/staff/dashboard/", "/staff/intake/", "/staff/follow-ups/", "/staff/pipeline/", "/staff/students/",
               "/staff/startups/", "/staff/walk-in/", "/staff/notifications/", "/staff/export/startups.csv"]
ADMIN_PAGES = ["/staff/team/", "/staff/import/"]


@pytest.mark.parametrize("url", STAFF_PAGES + ADMIN_PAGES)
def test_anonymous_is_sent_to_sign_in(client, reference, url):
    response = client.get(url)
    assert response.status_code == 302 and response.url.startswith("/staff/login/")


@pytest.mark.parametrize("url", STAFF_PAGES + ADMIN_PAGES)
def test_user_without_role_is_refused(client, make_user, url):
    client.force_login(make_user("nobody"))
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("url", STAFF_PAGES)
def test_coach_can_use_staff_pages(client, make_user, url):
    client.force_login(make_user("coachy", "Coach"))
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("url", ADMIN_PAGES)
def test_coach_cannot_use_admin_pages(client, make_user, url):
    client.force_login(make_user("coachy", "Coach"))
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("url", STAFF_PAGES + ADMIN_PAGES)
def test_admin_can_use_everything(client, make_user, url):
    client.force_login(make_user("boss", "Admin"))
    assert client.get(url).status_code == 200


def test_inactive_user_loses_access(client, make_user):
    user = make_user("coachy", "Coach")
    client.force_login(user)
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert client.get("/staff/dashboard/").status_code == 302


def test_configuration_admin_permissions(client, make_user):
    coach, boss = make_user("coachy", "Coach"), make_user("boss", "Admin")
    set_role(coach, "Coach")
    set_role(boss, "Admin")
    client.force_login(coach)
    assert client.get("/admin/siteconfig/sitetext/").status_code == 200       # coaches edit form content
    assert client.get("/admin/siteconfig/appsettings/").status_code == 403    # ...but not system settings
    assert client.get("/admin/auth/user/").status_code == 403
    client.force_login(boss)
    assert client.get("/admin/siteconfig/appsettings/").status_code == 200
