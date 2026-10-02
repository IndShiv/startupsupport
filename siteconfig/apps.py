from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SiteconfigConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "siteconfig"
    verbose_name = _("Form content & settings")
