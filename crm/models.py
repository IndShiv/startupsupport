"""Students, startups, registrations and everything coaches record about them."""

from auditlog.registry import auditlog
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from siteconfig.models import Domain, PipelineStage, PrivacyStatement, StudyYear

from .validators import MaxWordsValidator, validate_phone, validate_student_number

DESCRIPTION_MAX_WORDS = 200
GRADUATION_TOPIC_MAX_WORDS = 100


class TimeStamped(models.Model):
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class Coach(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name=_("staff login"), null=True, blank=True, on_delete=models.SET_NULL, related_name="coach")
    first_name = models.CharField(_("first name"), max_length=100)
    last_name = models.CharField(_("last name"), max_length=100)
    email = models.EmailField(_("email"), blank=True)
    academy = models.CharField(_("academy"), max_length=20, blank=True, help_text=_("Shown on the coach card, e.g. ALE or ADSAI."))
    domains = models.ManyToManyField(Domain, verbose_name=_("home domains"), blank=True, related_name="coaches", help_text=_("Used to warn when a graduation-track student would get a coach from their own domain."))
    photo = models.ImageField(_("photo"), upload_to="coaches/", blank=True)
    background = models.TextField(_("background"), blank=True)
    help_with = models.TextField(_("I can help you with"), blank=True)
    active = models.BooleanField(_("active"), default=True, help_text=_("Inactive coaches are hidden on the form and cannot be assigned."))
    order = models.PositiveIntegerField(_("order"), default=0)

    class Meta:
        ordering = ["order", "first_name", "last_name"]
        verbose_name = _("coach")
        verbose_name_plural = _("coaches")

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def initials(self):
        return (self.first_name[:1] + self.last_name.split()[-1][:1]).upper()

    def caseload(self):
        return self.startups.filter(archived_at__isnull=True, stage__is_closed=False).count()


class StudentQuerySet(models.QuerySet):
    def current(self):
        """Not merged into another record and not anonymised."""
        return self.filter(merged_into__isnull=True, anonymised_at__isnull=True)


class Student(TimeStamped):
    first_name = models.CharField(_("first name"), max_length=100)
    last_name = models.CharField(_("last name"), max_length=100)
    student_number = models.CharField(_("student number"), max_length=6, blank=True, db_index=True, validators=[validate_student_number])
    email = models.EmailField(_("email"), db_index=True)
    phone = models.CharField(_("phone number"), max_length=20, validators=[validate_phone])
    domain = models.ForeignKey(Domain, verbose_name=_("domain"), on_delete=models.PROTECT, related_name="students")
    study_year = models.ForeignKey(StudyYear, verbose_name=_("study year"), on_delete=models.PROTECT, related_name="students")
    archived_at = models.DateTimeField(_("archived at"), null=True, blank=True)
    anonymised_at = models.DateTimeField(_("anonymised at"), null=True, blank=True)
    merged_into = models.ForeignKey("self", verbose_name=_("merged into"), null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_from")

    objects = StudentQuerySet.as_manager()

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = _("student")
        verbose_name_plural = _("students")

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def is_employee(self):
        return self.domain.is_employee

    @property
    def on_graduation_track(self):
        return self.study_year.is_graduation_track


class Tag(models.Model):
    name = models.CharField(_("name"), max_length=50, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("tag")
        verbose_name_plural = _("tags")

    def __str__(self):
        return self.name


class StartupQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived_at__isnull=True, stage__is_closed=False)


class Startup(TimeStamped):
    name = models.CharField(_("startup name"), max_length=200, blank=True, help_text=_("Staff only. Leave empty until the startup has a name."))
    description = models.TextField(_("business (idea) description"), validators=[MaxWordsValidator(DESCRIPTION_MAX_WORDS)])
    has_paying_customers = models.BooleanField(_("has paying customers"), null=True, blank=True)
    idea_validated = models.BooleanField(_("idea validated with target customers"), null=True, blank=True)
    goals = models.TextField(_("goals for the coach track"), blank=True)
    stage = models.ForeignKey(PipelineStage, verbose_name=_("stage"), on_delete=models.PROTECT, related_name="startups")
    assigned_coach = models.ForeignKey(Coach, verbose_name=_("assigned coach"), null=True, blank=True, on_delete=models.SET_NULL, related_name="startups")
    founders = models.ManyToManyField(Student, through="Founder", related_name="startups", verbose_name=_("founders"))
    tags = models.ManyToManyField(Tag, verbose_name=_("tags"), blank=True, related_name="startups")
    kvk_number = models.CharField(_("KvK number"), max_length=8, blank=True)
    archived_at = models.DateTimeField(_("archived at"), null=True, blank=True)
    last_activity_at = models.DateTimeField(_("last activity"), null=True, blank=True)

    objects = StartupQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("startup / idea")
        verbose_name_plural = _("startups / ideas")

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        if self.name:
            return self.name
        words = self.description.split()
        return " ".join(words[:6]) + ("…" if len(words) > 6 else "")


class Founder(models.Model):
    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="founder_links")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="founder_links")
    role = models.CharField(_("role"), max_length=100, blank=True)
    joined_on = models.DateField(_("joined on"), default=timezone.localdate)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["startup", "student"], name="unique_founder")]
        verbose_name = _("founder")
        verbose_name_plural = _("founders")

    def __str__(self):
        return f"{self.student} – {self.startup}"


class RegistrationQuerySet(models.QuerySet):
    def open(self):
        return self.filter(student__anonymised_at__isnull=True, student__archived_at__isnull=True, startup__archived_at__isnull=True)

    def awaiting_intake(self):
        """The 10-working-day clock is running: nothing scheduled or held yet."""
        return self.open().filter(intake_scheduled_on__isnull=True, intake_held_on__isnull=True)

    def intake_scheduled(self):
        return self.open().filter(intake_scheduled_on__isnull=False, intake_held_on__isnull=True)

    def intake_done(self):
        return self.filter(intake_held_on__isnull=False)


class Registration(models.Model):
    """One form submission (or walk-in / imported response), kept as submitted."""

    class Source(models.TextChoices):
        FORM = "form", _("Registration form")
        WALK_IN = "walk_in", _("Walk-in (added by staff)")
        IMPORT = "import", _("Microsoft Forms import")

    student = models.ForeignKey(Student, verbose_name=_("student"), on_delete=models.PROTECT, related_name="registrations")
    startup = models.ForeignKey(Startup, verbose_name=_("startup / idea"), on_delete=models.PROTECT, related_name="registrations")
    submitted_at = models.DateTimeField(_("submitted at"), default=timezone.now, db_index=True)
    source = models.CharField(_("source"), max_length=10, choices=Source.choices, default=Source.FORM)
    preferred_coach = models.ForeignKey(Coach, verbose_name=_("preferred coach"), null=True, blank=True, on_delete=models.SET_NULL, related_name="preferred_by", help_text=_("Empty = no preference."))
    comments = models.TextField(_("comments"), blank=True)
    answers = models.JSONField(_("answers as submitted"), default=dict, blank=True)
    consent_at = models.DateTimeField(_("privacy consent given at"), null=True, blank=True)
    privacy_statement = models.ForeignKey(PrivacyStatement, verbose_name=_("privacy statement version"), null=True, blank=True, on_delete=models.PROTECT)
    forms_response_id = models.CharField(_("Microsoft Forms response ID"), max_length=50, null=True, blank=True, unique=True)
    is_duplicate_student = models.BooleanField(_("matched an existing student"), default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("created by"), null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    intake_deadline = models.DateField(_("intake deadline"), null=True, blank=True, db_index=True)
    intake_scheduled_on = models.DateField(_("intake scheduled on"), null=True, blank=True, help_text=_("The date the intake was arranged; this stops the 10-working-day clock."))
    intake_planned_at = models.DateTimeField(_("intake planned for"), null=True, blank=True, help_text=_("When the intake chat will take place."))
    intake_held_on = models.DateField(_("intake held on"), null=True, blank=True)
    intake_coach = models.ForeignKey(Coach, verbose_name=_("intake held by"), null=True, blank=True, on_delete=models.SET_NULL, related_name="intakes")

    objects = RegistrationQuerySet.as_manager()

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = _("registration")
        verbose_name_plural = _("registrations")

    def __str__(self):
        return f"{self.student} – {self.submitted_at:%Y-%m-%d}"


class GraduationTrack(models.Model):
    class Approval(models.TextChoices):
        YES = "yes", _("Yes")
        NOT_YET = "not_yet", _("No, not yet")

    registration = models.OneToOneField(Registration, on_delete=models.CASCADE, related_name="graduation")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="graduation_tracks")
    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="graduation_tracks")
    approval = models.CharField(_("programme approval to graduate with own company"), max_length=10, choices=Approval.choices)
    topic = models.TextField(_("graduation assignment topic"), validators=[MaxWordsValidator(GRADUATION_TOPIC_MAX_WORDS)])
    supervisor_name = models.CharField(_("graduation supervisor"), max_length=200)
    hand_in_date = models.DateField(_("intended hand-in date of final product"))

    class Meta:
        ordering = ["hand_in_date"]
        verbose_name = _("graduation track")
        verbose_name_plural = _("graduation tracks")

    def __str__(self):
        return f"{self.student} – {self.hand_in_date}"

    @property
    def approval_missing(self):
        return self.approval == self.Approval.NOT_YET


class Activity(models.Model):
    # Written by the system (intake recorded, stage changed); shown read-only in the log.
    SYSTEM_KINDS = ("intake", "stage")

    class Kind(models.TextChoices):
        NOTE = "note", _("Note")
        MEETING = "meeting", _("Meeting")
        EMAIL = "email", _("Email")
        EVENT = "event", _("Event attendance")
        REFERRAL = "referral", _("Referral")
        INTAKE = "intake", _("Intake")
        STAGE = "stage", _("Stage change")

    startup = models.ForeignKey(Startup, verbose_name=_("startup"), on_delete=models.CASCADE, related_name="activities")
    kind = models.CharField(_("type"), max_length=10, choices=Kind.choices, default=Kind.NOTE)
    date = models.DateField(_("date"), default=timezone.localdate)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("author"), null=True, on_delete=models.SET_NULL, related_name="activities")
    body = models.TextField(_("details"))
    admin_only = models.BooleanField(_("visible to admins only"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = _("activity")
        verbose_name_plural = _("activities")

    def __str__(self):
        return f"{self.get_kind_display()} {self.date}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.kind == self.Kind.STAGE:
            return  # bookkeeping, not contact with the startup: doesn't reset "no activity for X weeks"
        Startup.objects.filter(pk=self.startup_id).filter(
            Q(last_activity_at__isnull=True) | Q(last_activity_at__lt=self.created_at)
        ).update(last_activity_at=self.created_at)


class FollowUpQuerySet(models.QuerySet):
    def open(self):
        return self.filter(done_at__isnull=True)

    def for_user(self, user):
        """Assigned to the user, or unassigned on a startup they coach (e.g. automatic reminders)."""
        coach = getattr(user, "coach", None)
        query = Q(assigned_to=user)
        if coach is not None:
            query |= Q(assigned_to__isnull=True) & (
                Q(startup__assigned_coach=coach) | Q(startup__isnull=True, student__startups__assigned_coach=coach)
            )
        return self.filter(query).distinct()

    def due_by(self, day):
        return self.filter(due_date__lte=day)


class FollowUp(models.Model):
    startup = models.ForeignKey(Startup, verbose_name=_("startup"), null=True, blank=True, on_delete=models.CASCADE, related_name="follow_ups")
    student = models.ForeignKey(Student, verbose_name=_("student"), null=True, blank=True, on_delete=models.CASCADE, related_name="follow_ups")
    title = models.CharField(_("title"), max_length=200)
    notes = models.TextField(_("notes"), blank=True)
    due_date = models.DateField(_("due date"), db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("assigned to"), null=True, blank=True, on_delete=models.SET_NULL, related_name="follow_ups")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("created by"), null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    auto_reason = models.CharField(_("created automatically because"), max_length=50, blank=True)
    done_at = models.DateTimeField(_("done at"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FollowUpQuerySet.as_manager()

    class Meta:
        ordering = ["due_date"]
        verbose_name = _("follow-up")
        verbose_name_plural = _("follow-ups")

    def __str__(self):
        return self.title

    @property
    def is_done(self):
        return self.done_at is not None


class OutgoingEmail(models.Model):
    """Log of emails the app sent. Only metadata is kept, never the message body."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")

    kind = models.CharField(_("email"), max_length=50)
    registration = models.ForeignKey(Registration, verbose_name=_("registration"), null=True, blank=True, on_delete=models.SET_NULL, related_name="emails")
    to = models.CharField(_("to"), max_length=254)
    subject = models.CharField(_("subject"), max_length=255)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(_("error"), blank=True)
    attempts = models.PositiveSmallIntegerField(_("attempts"), default=0)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("sent email")
        verbose_name_plural = _("sent emails")

    def __str__(self):
        return f"{self.subject} → {self.to}"


class Notification(models.Model):
    """In-app notification for a staff user."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=300)
    url = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.message


auditlog.register(Coach, exclude_fields=["photo"])
auditlog.register(Student, mask_fields=["student_number", "phone"])
auditlog.register(Startup, m2m_fields={"tags"})
auditlog.register(Founder)
auditlog.register(Registration, exclude_fields=["answers"])
auditlog.register(GraduationTrack)
auditlog.register(Activity)
auditlog.register(FollowUp)
