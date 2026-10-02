from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="staff/login.html", redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("intake/", views.intake_queue, name="intake_queue"),
    path("intake/<int:pk>/", views.intake_detail, name="intake_detail"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/read/", views.notifications_read, name="notifications_read"),
    path("notifications/<int:pk>/", views.notification_open, name="notification_open"),
]
