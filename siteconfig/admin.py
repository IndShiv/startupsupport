from django.contrib import admin, messages
from django.utils.html import format_html_join
from django.utils.translation import gettext_lazy as _

from .models import AppSettings, ClosureDay, Domain, EmailTemplate, Partner, PipelineStage, PrivacyStatement, SiteText, StudyYear


class OrderedOptionAdmin(admin.ModelAdmin):
    list_display = ["name", "order", "active"]
    list_editable = ["order", "active"]


@admin.register(Domain)
class DomainAdmin(OrderedOptionAdmin):
    list_display = ["name", "academy_code", "order", "active", "is_employee"]


@admin.register(StudyYear)
class StudyYearAdmin(OrderedOptionAdmin):
    list_display = ["name", "order", "active", "is_graduation_track"]


@admin.register(PipelineStage)
class PipelineStageAdmin(OrderedOptionAdmin):
    list_display = ["name", "order", "active", "colour", "is_initial", "is_closed", "marks_intake_scheduled", "marks_intake_done"]


@admin.register(SiteText)
class SiteTextAdmin(admin.ModelAdmin):
    list_display = ["key", "title", "help"]
    search_fields = ["key", "title", "body"]


@admin.register(PrivacyStatement)
class PrivacyStatementAdmin(admin.ModelAdmin):
    list_display = ["version", "published_at", "created_at"]

    def get_readonly_fields(self, request, obj=None):
        # A published version is what students consented to: never edit it, publish a new one.
        if obj and obj.published_at:
            return ["version", "body", "published_at"]
        return []


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ["name", "url", "active", "order"]
    list_editable = ["active", "order"]


@admin.register(ClosureDay)
class ClosureDayAdmin(admin.ModelAdmin):
    list_display = ["date", "name"]
    date_hierarchy = "date"


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ["key", "language", "subject", "updated_at"]
    list_filter = ["key", "language"]
    readonly_fields = ["available_placeholders"]
    fields = ["key", "language", "available_placeholders", "subject", "body"]
    actions = ["send_test"]

    @admin.display(description=_("Available placeholders"))
    def available_placeholders(self, obj):
        if not obj or not obj.key:
            return _("Save first to see the placeholders for this email.")
        names = EmailTemplate.PLACEHOLDERS.get(obj.key, [])
        return format_html_join(", ", "<code>{{{{ {} }}}}</code>", ((n,) for n in names))

    @admin.action(description=_("Send a test to my own email address"))
    def send_test(self, request, queryset):
        from crm.email_preview import send_test_email

        if not request.user.email:
            self.message_user(request, _("Your user account has no email address."), messages.ERROR)
            return
        for template in queryset:
            send_test_email(template, request.user.email)
        self.message_user(request, _("Test email(s) sent to %(email)s.") % {"email": request.user.email})
