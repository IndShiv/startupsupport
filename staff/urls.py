from django.contrib.auth import views as auth_views
from django.urls import path

from . import views, views_pipeline as pipeline, views_records as records

app_name = "staff"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="staff/login.html", redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("intake/", views.intake_queue, name="intake_queue"),
    path("intake/<int:pk>/", views.intake_detail, name="intake_detail"),
    path("students/", records.student_list, name="student_list"),
    path("students/<int:pk>/", records.student_detail, name="student_detail"),
    path("students/<int:pk>/edit/", records.student_edit, name="student_edit"),
    path("students/<int:pk>/archive/", records.student_archive, name="student_archive"),
    path("students/<int:pk>/merge/", records.student_merge_search, name="student_merge_search"),
    path("students/<int:pk>/merge/<int:other_pk>/", records.student_merge, name="student_merge"),
    path("startups/", records.startup_list, name="startup_list"),
    path("startups/new/", records.startup_edit, name="startup_create"),
    path("startups/<int:pk>/", records.startup_detail, name="startup_detail"),
    path("startups/<int:pk>/edit/", records.startup_edit, name="startup_edit"),
    path("startups/<int:pk>/archive/", records.startup_archive, name="startup_archive"),
    path("startups/<int:pk>/founders/add/", records.founder_add, name="founder_add"),
    path("startups/<int:pk>/founders/<int:founder_pk>/remove/", records.founder_remove, name="founder_remove"),
    path("graduation/<int:pk>/edit/", records.graduation_edit, name="graduation_edit"),
    path("walk-in/", records.walk_in, name="walk_in"),
    path("pipeline/", pipeline.pipeline, name="pipeline"),
    path("pipeline/<int:pk>/move/", pipeline.move, name="pipeline_move"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/read/", views.notifications_read, name="notifications_read"),
    path("notifications/<int:pk>/", views.notification_open, name="notification_open"),
]
