"""Test-environment safeguards: banner, no search-engine indexing, Render host names."""

import pytest

pytestmark = pytest.mark.django_db

BANNER = "Do not enter real student details"


def test_no_banner_normally(client, reference):
    page = client.get("/register/")
    assert BANNER not in page.content.decode()
    assert "X-Robots-Tag" not in page  # the public form may be found by students
    assert client.get("/staff/login/")["X-Robots-Tag"] == "noindex, nofollow"


def test_demo_mode_banner_and_noindex(client, reference, settings, make_user):
    settings.DEMO_MODE = True
    for url in ("/register/", "/staff/login/"):
        response = client.get(url)
        text = response.content.decode()
        assert BANNER in text and '<meta name="robots" content="noindex, nofollow">' in text
        assert response["X-Robots-Tag"] == "noindex, nofollow"
    client.force_login(make_user("boss", "Admin"))
    assert BANNER in client.get("/staff/students/").content.decode()


def test_robots_txt(client, settings):
    assert "Disallow: /staff/" in client.get("/robots.txt").content.decode()
    settings.DEMO_MODE = True
    assert client.get("/robots.txt").content.decode() == "User-agent: *\nDisallow: /\n"


def test_demo_mode_banner_in_configuration_admin(client, reference, settings, django_user_model):
    admin = django_user_model.objects.create_superuser("root", "root@example.org", "pw")
    client.force_login(admin)
    assert BANNER not in client.get("/admin/").content.decode()
    settings.DEMO_MODE = True
    assert BANNER in client.get("/admin/").content.decode()
    assert BANNER in client.get("/admin/crm/student/").content.decode()
