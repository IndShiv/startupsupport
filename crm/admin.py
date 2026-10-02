from django.contrib import admin

from .models import Activity, Coach, Founder, FollowUp, GraduationTrack, Notification, Registration, Startup, Student, Tag


@admin.register(Coach)
class CoachAdmin(admin.ModelAdmin):
    list_display = ["full_name", "academy", "active", "order", "caseload"]
    list_editable = ["active", "order"]
    filter_horizontal = ["domains"]
    search_fields = ["first_name", "last_name", "email"]


class FounderInline(admin.TabularInline):
    model = Founder
    extra = 0
    autocomplete_fields = ["student"]


class RegistrationInline(admin.TabularInline):
    model = Registration
    extra = 0
    fields = ["submitted_at", "source", "student", "preferred_coach", "intake_deadline", "intake_scheduled_on", "intake_held_on"]
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ["full_name", "student_number", "email", "domain", "study_year", "created_at"]
    list_filter = ["domain", "study_year"]
    search_fields = ["first_name", "last_name", "student_number", "email"]


@admin.register(Startup)
class StartupAdmin(admin.ModelAdmin):
    list_display = ["display_name", "stage", "assigned_coach", "has_paying_customers", "idea_validated", "created_at"]
    list_filter = ["stage", "assigned_coach", "tags"]
    search_fields = ["name", "description"]
    filter_horizontal = ["tags"]
    inlines = [FounderInline, RegistrationInline]


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ["student", "submitted_at", "source", "preferred_coach", "intake_deadline", "intake_scheduled_on", "is_duplicate_student"]
    list_filter = ["source", "is_duplicate_student"]
    search_fields = ["student__first_name", "student__last_name", "student__student_number", "forms_response_id"]
    date_hierarchy = "submitted_at"
    autocomplete_fields = ["student"]
    readonly_fields = ["answers", "consent_at", "privacy_statement"]


@admin.register(GraduationTrack)
class GraduationTrackAdmin(admin.ModelAdmin):
    list_display = ["student", "approval", "hand_in_date", "supervisor_name"]
    list_filter = ["approval"]


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ["startup", "kind", "date", "author", "admin_only"]
    list_filter = ["kind", "admin_only"]


@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    list_display = ["title", "due_date", "assigned_to", "done_at", "auto_reason"]
    list_filter = ["assigned_to"]


admin.site.register(Tag)
admin.site.register(Notification)
admin.site.site_header = "BUSS Startup Support"
admin.site.site_title = "BUSS admin"
