"""Configuration that admins (and coaches) edit without a code change."""

from auditlog.registry import auditlog
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class OrderedOption(models.Model):
    name = models.CharField(_("name"), max_length=100, unique=True)
    order = models.PositiveIntegerField(_("order"), default=0)
    active = models.BooleanField(_("active"), default=True, help_text=_("Inactive options are hidden on the form but kept on existing records."))

    class Meta:
        abstract = True
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Domain(OrderedOption):
    academy_code = models.CharField(_("academy code"), max_length=10, blank=True, help_text=_("e.g. ALE, AFT, HFM, AGM, BE, LOG, ADSAI"))
    is_employee = models.BooleanField(_("is the 'I am an employee' option"), default=False)

    class Meta(OrderedOption.Meta):
        verbose_name = _("domain")
        verbose_name_plural = _("domains")


class StudyYear(OrderedOption):
    is_graduation_track = models.BooleanField(
        _("graduating within own company"),
        default=False,
        help_text=_("Choosing this option shows the graduation section on the form."),
    )

    class Meta(OrderedOption.Meta):
        verbose_name = _("study year")
        verbose_name_plural = _("study years")


class PipelineStage(OrderedOption):
    colour = models.CharField(_("colour"), max_length=7, default="#6b7280", help_text=_("Hex colour, e.g. #e8730c"))
    is_initial = models.BooleanField(_("initial stage for new registrations"), default=False)
    is_closed = models.BooleanField(_("closed stage"), default=False, help_text=_("e.g. Alumni / Stopped: no longer counted as active caseload."))
    marks_intake_scheduled = models.BooleanField(_("moving here means the intake is scheduled"), default=False)
    marks_intake_done = models.BooleanField(_("moving here means the intake is done"), default=False)

    class Meta(OrderedOption.Meta):
        verbose_name = _("pipeline stage")
        verbose_name_plural = _("pipeline stages")

    @classmethod
    def initial(cls):
        return cls.objects.filter(is_initial=True).order_by("order").first() or cls.objects.order_by("order").first()


class SiteText(models.Model):
    """A block of editable text, identified by a fixed key used in templates."""

    key = models.SlugField(_("key"), max_length=60, unique=True)
    title = models.CharField(_("title"), max_length=200, blank=True)
    body = models.TextField(_("body"), blank=True, help_text=_("Plain text; blank lines start a new paragraph, lines starting with '- ' become a list."))
    help = models.CharField(_("where this text is used"), max_length=200, blank=True)

    class Meta:
        ordering = ["key"]
        verbose_name = _("page text")
        verbose_name_plural = _("page texts")

    def __str__(self):
        return self.key

    @classmethod
    def get(cls, key, default=""):
        obj = cls.objects.filter(key=key).first()
        return obj.body if obj else default


class PrivacyStatement(models.Model):
    """Versioned privacy text. Consent records point at the version a student agreed to."""

    version = models.CharField(_("version"), max_length=20, unique=True)
    body = models.TextField(_("body"))
    published_at = models.DateTimeField(_("published at"), null=True, blank=True, help_text=_("Leave empty while drafting. The latest published version is shown on the form."))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name = _("privacy statement")
        verbose_name_plural = _("privacy statements")

    def __str__(self):
        return f"v{self.version}"

    @classmethod
    def current(cls):
        return cls.objects.filter(published_at__isnull=False).order_by("-published_at").first()


class ClosureDay(models.Model):
    """Non-working days on top of Dutch public holidays (e.g. BUas Christmas closure)."""

    date = models.DateField(_("date"), unique=True)
    name = models.CharField(_("name"), max_length=100)

    class Meta:
        ordering = ["date"]
        verbose_name = _("closure day")
        verbose_name_plural = _("closure days")

    def __str__(self):
        return f"{self.date:%Y-%m-%d} {self.name}"


class AppSettings(models.Model):
    """Singleton with tunable business rules."""

    class NotificationMode(models.TextChoices):
        EMAIL = "email", _("Email")
        IN_APP = "in_app", _("In-app")
        BOTH = "both", _("Email and in-app")

    intake_working_days = models.PositiveSmallIntegerField(_("intake within (working days)"), default=10)
    intake_due_soon_days = models.PositiveSmallIntegerField(_("highlight when due within (working days)"), default=2)
    staff_notification_mode = models.CharField(_("new registration notifications"), max_length=10, choices=NotificationMode.choices, default=NotificationMode.BOTH)
    staff_notification_email = models.EmailField(_("staff notification address"), default="buss-placeholder@example.org")
    retention_years = models.PositiveSmallIntegerField(_("flag for anonymisation after (years inactive or alumni)"), default=2)
    inactivity_weeks = models.PositiveSmallIntegerField(_("dashboard: no activity for (weeks)"), default=6)
    rate_limit_per_hour = models.PositiveSmallIntegerField(_("max registrations per hour per IP"), default=5)

    class Meta:
        verbose_name = _("app settings")
        verbose_name_plural = _("app settings")

    def __str__(self):
        return str(_("App settings"))

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("The settings record cannot be deleted."))

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


for model in (Domain, StudyYear, PipelineStage, SiteText, PrivacyStatement, ClosureDay, AppSettings):
    auditlog.register(model)
