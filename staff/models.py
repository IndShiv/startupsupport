from django.conf import settings
from django.db import models


class EntraIdentity(models.Model):
    """Links a staff user to their Microsoft Entra ID account (object ID never changes; email can)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entra")
    oid = models.CharField("Entra object ID", max_length=64, unique=True)
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Entra ID account"

    def __str__(self):
        return f"{self.user} ({self.oid})"
