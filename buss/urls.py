from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from staff.views_auth import admin_login_redirect

admin.site.login = admin_login_redirect

urlpatterns = [
    path("admin/", admin.site.urls),
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("staff/", include("staff.urls")),
    path("", include("public.urls")),
    path("", RedirectView.as_view(pattern_name="public:register", permanent=False)),
    # Media holds only coach photos (public on the form anyway), so Django serves it directly.
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
