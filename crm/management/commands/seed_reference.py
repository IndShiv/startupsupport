"""Create the reference data the app needs: option lists, stages, texts, coaches, roles.

Safe to run repeatedly: existing rows are left as they are (admins may have
edited them), only missing ones are created.
"""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from crm.models import Coach
from siteconfig.models import AppSettings, Domain, Partner, PipelineStage, PrivacyStatement, SiteText, StudyYear

DOMAINS = [
    # (name, academy code, is_employee)
    ("Leisure & Events", "ALE", False),
    ("Tourism", "AFT", False),
    ("Media", "AGM", False),
    ("Games", "AGM", False),
    ("Hotel", "HFM", False),
    ("Facility", "HFM", False),
    ("Built Environment", "BE", False),
    ("Logistics", "LOG", False),
    ("Data Science & AI", "ADSAI", False),
    ("I am an employee", "", True),
]

STUDY_YEARS = [
    ("Year 1", False),
    ("Year 2", False),
    ("Year 3", False),
    ("Year 4", False),
    ("Year 4 and graduating within own company", True),
    ("BUas Master", False),
    ("Not applicable", False),
]

STAGES = [
    # name, colour, initial, closed, marks scheduled, marks done
    ("Registered", "#6b7280", True, False, False, False),
    ("Intake scheduled", "#2563eb", False, False, True, False),
    ("Intake done", "#0891b2", False, False, False, True),
    ("Coaching", "#e8730c", False, False, False, False),
    ("Graduated (own company)", "#7c3aed", False, False, False, False),
    ("Registered at KvK", "#16a34a", False, False, False, False),
    ("Alumni", "#374151", False, True, False, False),
    ("Stopped", "#9ca3af", False, True, False, False),
]

# (first, last, academy, domain names) — from "Meet the coaches". Tijs van Es has no home academy.
COACHES = [
    ("Patrice", "Staal", "HFM", ["Hotel", "Facility"]),
    ("Gerben", "Beijneveld", "HFM", ["Hotel", "Facility"]),
    ("Ben", "Veenstra", "AFT", ["Tourism"]),
    ("Remco", "Bergwerff", "AFT", ["Tourism"]),
    ("Shival", "Indermun", "ADSAI", ["Data Science & AI"]),
    ("Joyce", "Ridderhof", "ALE", ["Leisure & Events"]),
    ("Roeland", "Bottema", "ALE", ["Leisure & Events"]),
    ("Erik", "van Diffelen", "LOG", ["Logistics"]),
    ("Marc", "Holvoet", "BE", ["Built Environment"]),
    ("Hans", "de Nie", "AGM", ["Games", "Media"]),
    ("Tijs", "van Es", "", []),
]

SITE_TEXTS = {
    "form_intro": (
        "Register for BUas Startup Support",
        "Registration takes about 6 minutes.\n\n"
        "Everyone who registers is invited for an intake chat with one of our coaches within 10 working days. "
        "We'd love to hear your ambitions, see how we can support you, and connect you with fellow (student) entrepreneurs.",
        "Introduction at the top of the registration form",
    ),
    "minor_note": (
        "Following the minor \"Build your own business\"?",
        "Students in the minor \"Build your own business\" already have a personal coaching track. "
        "You are very welcome at BUSS events and activities!",
        "Note below the introduction",
    ),
    "coach_note": (
        "About choosing a coach",
        "- Because of limited availability we can't guarantee you will get your preferred coach.\n"
        "- Students graduating within their own company are matched with a coach from a different domain than their own study.",
        "Note above the coach cards",
    ),
    "graduation_approval_notice": (
        "Approval needed",
        "Please arrange approval from your programme as soon as possible and inform your BUSS coach once you have it.",
        "Shown when a graduation-track student answers 'No, not yet' to programme approval",
    ),
    "thank_you": (
        "Thank you for registering!",
        "We have received your registration. A BUSS coach will contact you within 10 working days to plan your intake chat.\n\n"
        "You will also receive a confirmation email with a summary of your answers.",
        "Thank-you page after submitting",
    ),
    "contact": (
        "Questions?",
        "Email the BUSS team at startupsupport@buas.nl.",
        "Footer of public pages",
    ),
}

PRIVACY_V1 = """DRAFT — to be reviewed by the BUas privacy officer before go-live.

What we store
Your name, student number, BUas email address, phone number, domain and study year; the description of your business idea and your answers on this form; if you graduate within your own company: your graduation topic, supervisor and hand-in date; and the notes our coaches make during your coaching track.

Why
To invite you for an intake, match you with a coach, coach you, connect you with fellow entrepreneurs and invite you to BUSS activities. We also use anonymised totals to report on and improve our services.

Who can see it
Only BUSS coaches and BUSS administrators at Breda University of Applied Sciences. We do not share your data with third parties.

How long we keep it
Until 2 years after your last contact with BUSS or after you become an alumnus. After that your data is anonymised.

Your rights
You can ask to see, correct, export or delete your data at any time by emailing the BUSS team at startupsupport@buas.nl.
"""

COACH_EDITABLE_MODELS = {
    # app_label: {model: actions}
    "crm": {
        "student": ["view", "add", "change"],
        "startup": ["view", "add", "change"],
        "founder": ["view", "add", "change", "delete"],
        "registration": ["view", "add", "change"],
        "graduationtrack": ["view", "add", "change"],
        "activity": ["view", "add", "change"],
        "followup": ["view", "add", "change", "delete"],
        "tag": ["view", "add", "change"],
        "coach": ["view", "change"],
    },
    # Coaches may edit form content (decision 2 Oct 2026); system settings stay admin-only.
    "siteconfig": {
        "domain": ["view", "add", "change"],
        "studyyear": ["view", "add", "change"],
        "sitetext": ["view", "change"],
        "pipelinestage": ["view"],
        "privacystatement": ["view"],
        "closureday": ["view", "add", "change", "delete"],
        "partner": ["view", "add", "change"],
    },
}


class Command(BaseCommand):
    help = "Create reference data (domains, study years, stages, page texts, privacy statement, coaches, roles)."

    @transaction.atomic
    def handle(self, *args, **options):
        for order, (name, code, is_employee) in enumerate(DOMAINS):
            Domain.objects.get_or_create(name=name, defaults={"academy_code": code, "is_employee": is_employee, "order": order * 10})

        for order, (name, grad) in enumerate(STUDY_YEARS):
            StudyYear.objects.get_or_create(name=name, defaults={"is_graduation_track": grad, "order": order * 10})

        for order, (name, colour, initial, closed, sched, done) in enumerate(STAGES):
            PipelineStage.objects.get_or_create(
                name=name,
                defaults={"order": order * 10, "colour": colour, "is_initial": initial, "is_closed": closed,
                          "marks_intake_scheduled": sched, "marks_intake_done": done},
            )

        for key, (title, body, help_text) in SITE_TEXTS.items():
            SiteText.objects.get_or_create(key=key, defaults={"title": title, "body": body, "help": help_text})

        if not PrivacyStatement.objects.exists():
            PrivacyStatement.objects.create(version="1.0-draft", body=PRIVACY_V1, published_at=timezone.now())

        AppSettings.load()
        self._seed_partners()
        self._seed_coaches()
        self._seed_groups()
        self.stdout.write(self.style.SUCCESS("Reference data is in place."))

    def _seed_partners(self):
        partner, created = Partner.objects.get_or_create(name="B'WISE", defaults={"order": 10})
        if created:
            logo = Path(settings.BASE_DIR) / "static" / "img" / "partners-bwise.png"
            with logo.open("rb") as fh:
                partner.logo.save("bwise.png", File(fh), save=True)

    def _seed_coaches(self):
        private_dir = Path(settings.BASE_DIR) / "seed_data" / "private"
        profiles = {}
        if (private_dir / "coaches.json").exists():
            profiles = json.loads((private_dir / "coaches.json").read_text(encoding="utf-8"))

        for order, (first, last, academy, domain_names) in enumerate(COACHES):
            coach, created = Coach.objects.get_or_create(
                first_name=first, last_name=last, defaults={"academy": academy, "order": order * 10}
            )
            if not created:
                continue
            coach.domains.set(Domain.objects.filter(name__in=domain_names))
            slug = f"{first} {last}".lower().replace(" ", "-")
            profile = profiles.get(slug, {})
            coach.background = profile.get("background", "")
            coach.help_with = profile.get("help_with", "")
            photo = private_dir / "coaches" / f"{slug}.jpg"
            if photo.exists():
                with photo.open("rb") as fh:
                    coach.photo.save(f"{slug}.jpg", File(fh), save=False)
            coach.save()

    def _seed_groups(self):
        admin_group, _ = Group.objects.get_or_create(name="Admin")
        admin_group.permissions.set(
            Permission.objects.filter(content_type__app_label__in=["crm", "siteconfig", "auth", "auditlog"])
        )
        coach_group, _ = Group.objects.get_or_create(name="Coach")
        perms = []
        for app_label, models in COACH_EDITABLE_MODELS.items():
            for model, actions in models.items():
                codenames = [f"{action}_{model}" for action in actions]
                perms += list(Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames))
        coach_group.permissions.set(perms)
