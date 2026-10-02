from django.contrib import admin

from .models import AppSettings, ClosureDay, Domain, Partner, PipelineStage, PrivacyStatement, SiteText, StudyYear


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
