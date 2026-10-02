from django.urls import path

from . import views

app_name = "public"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("register/thanks/", views.thanks, name="thanks"),
    path("privacy/", views.privacy, name="privacy"),
]
