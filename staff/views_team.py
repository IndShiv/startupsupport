"""Team page: who may use the staff app, and in which role (admins only)."""

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from crm.models import Coach

from .roles import ROLES, get_role, set_role
from .views_import import admin_required

User = get_user_model()


class TeamMemberForm(forms.Form):
    email = forms.EmailField(label=gettext_lazy("BUas email address"), help_text=gettext_lazy("They sign in with this BUas account."))
    first_name = forms.CharField(label=gettext_lazy("First name"), max_length=150)
    last_name = forms.CharField(label=gettext_lazy("Last name"), max_length=150)
    role = forms.ChoiceField(label=gettext_lazy("Role"), choices=[("", gettext_lazy("No access"))] + ROLES, required=False)
    coach = forms.ModelChoiceField(label=gettext_lazy("Coach profile"), queryset=Coach.objects.none(), required=False,
                                   help_text=gettext_lazy("Link the coach card shown on the registration form to this login."))
    active = forms.BooleanField(label=gettext_lazy("Active"), required=False, initial=True)

    def __init__(self, *args, instance=None, current_user=None, **kwargs):
        self.instance, self.current_user = instance, current_user
        super().__init__(*args, **kwargs)
        coach_q = Q(user__isnull=True)
        if instance is not None and hasattr(instance, "coach"):
            coach_q |= Q(pk=instance.coach.pk)
        self.fields["coach"].queryset = Coach.objects.filter(coach_q)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        clash = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(_("There is already a login with this email address."))
        return email

    def clean(self):
        data = super().clean()
        if self.instance is not None and self.instance == self.current_user:
            if data.get("role") != "Admin" or not data.get("active"):
                raise forms.ValidationError(_("You cannot remove your own admin role or deactivate yourself."))
        return data

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        user = self.instance
        if user is None:
            user = User.objects.create_user(username=data["email"], email=data["email"])
            user.set_unusable_password()  # signs in with the BUas account
        user.email = data["email"]
        user.first_name, user.last_name = data["first_name"], data["last_name"]
        user.is_active = data["active"]
        user.save()
        set_role(user, data["role"])
        Coach.objects.filter(user=user).exclude(pk=getattr(data["coach"], "pk", None)).update(user=None)
        if data["coach"]:
            data["coach"].user = user
            data["coach"].save(update_fields=["user"])
        return user


@admin_required
def team(request):
    users = User.objects.filter(Q(groups__name__in=["Admin", "Coach"]) | Q(is_superuser=True) | Q(is_staff=True)).distinct()
    members = [{"user": u, "role": get_role(u), "coach": getattr(u, "coach", None), "sso": hasattr(u, "entra")}
               for u in users.select_related("coach", "entra").order_by("-is_active", "first_name", "last_name")]
    return render(request, "staff/team.html", {"members": members})


@admin_required
def team_edit(request, pk=None):
    instance = get_object_or_404(User, pk=pk) if pk else None
    initial = {}
    if instance:
        initial = {"email": instance.email, "first_name": instance.first_name, "last_name": instance.last_name,
                   "role": get_role(instance), "coach": getattr(instance, "coach", None), "active": instance.is_active}
    form = TeamMemberForm(request.POST or None, instance=instance, current_user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, _("%(name)s saved.") % {"name": user.get_full_name() or user.email})
        return redirect("staff:team")
    title = _("Edit %(name)s") % {"name": instance.get_full_name() or instance.username} if instance else _("Add a team member")
    return render(request, "staff/record_form.html", {"form": form, "title": title, "back": ("staff:team", None)})
