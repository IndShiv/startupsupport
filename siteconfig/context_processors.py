from .models import Partner, SiteText


def public_page(request):
    """Footer content shared by all public pages. Evaluated lazily, so staff pages that don't use it pay nothing."""
    return {
        "partners": Partner.objects.filter(active=True),
        "contact": SiteText.objects.filter(key="contact").first,
    }
