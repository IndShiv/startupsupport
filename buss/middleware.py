from django.conf import settings

PRIVATE_PREFIXES = ("/staff/", "/admin/", "/oidc/", "/media/")


class NoIndexMiddleware:
    """Keep search engines away from the staff side always, and from the whole site on a test environment."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.DEMO_MODE or request.path.startswith(PRIVATE_PREFIXES):
            response["X-Robots-Tag"] = "noindex, nofollow"
        return response
