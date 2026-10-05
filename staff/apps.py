from django.apps import AppConfig


class StaffConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "staff"
    verbose_name = "Staff"

    def ready(self):
        from . import views_auth  # noqa: F401 - registers the sign-in signal handlers
