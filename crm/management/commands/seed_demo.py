"""Fill a development database with realistic *fake* students and startups.

Covers every domain, every study year, the graduation track (with and without
programme approval), duplicate registrations, a multi-founder startup and all
intake states (overdue, due soon, scheduled, held). Also creates dev logins.

Never run this against production: it refuses unless DJANGO_DEBUG is on, DEMO_MODE is
on (a test environment) or --force is given.

The login password is DEMO_PASSWORD from the environment; locally (DEBUG) it falls back to
the well-known development password. A public test server must set its own secret one.
`--reset` removes all students, startups and related records first (users are kept).
"""

import os

import random
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from faker import Faker

from auditlog.models import LogEntry

from crm.models import (
    Activity, Coach, ExportLog, Founder, FollowUp, GraduationTrack, ImportBatch, Notification, OutgoingEmail,
    PrivacyAction, Registration, Startup, Student, Tag,
)
from crm.workdays import add_working_days
from siteconfig.models import AppSettings, Domain, PipelineStage, PrivacyStatement, StudyYear

DEV_PASSWORD = "buss-dev-2026"

IDEAS = {
    "Leisure & Events": [
        ("Silent-disco walking tours through historic Breda, with local guides and storytelling on the headphones.", "Find a sustainable pricing model and partners such as VVV Breda."),
        ("A booking platform that matches small festivals with student volunteers and handles shift planning.", "Validate whether festival organisers will pay a fee per volunteer shift."),
        ("Escape rooms in shipping containers that travel to company events and school parties.", "Help with financing the first two containers and with permits."),
        ("Inclusive sports events for teenagers with a physical disability, organised with local clubs.", "Learn how to set up a social enterprise and apply for subsidies."),
    ],
    "Tourism": [
        ("Bike-and-boat holiday packages along the Biesbosch, bookable per day with luggage transfer.", "Test demand with German tourists and build a simple booking website."),
        ("A travel app for solo travellers that matches them with locals for a coffee or a walk.", "Figure out safety, privacy and how to earn money from the app."),
        ("Sustainable group trips to Portugal for students, with CO2-compensated travel by train.", "Register at the KvK and understand travel-organisation regulations (SGR)."),
        ("Audio stories for hotel guests about the neighbourhood, available through a QR code in the room.", "Find the first three hotels to pilot with."),
    ],
    "Media": [
        ("A video production studio that makes short-form social content for local SMEs.", "Get help with pricing, contracts and finding recurring clients."),
        ("A podcast network about student entrepreneurship, financed by sponsorships.", "Learn how to pitch to sponsors and grow the audience."),
        ("Drone filming for real estate agents in West-Brabant.", "Understand insurance, drone regulations and a first marketing plan."),
        ("An online magazine for international students in the Netherlands.", "Decide between advertising and a paid membership model."),
    ],
    "Games": [
        ("An indie studio developing a cosy farming game about Dutch polder life for PC and Switch.", "Find funding (e.g. Dutch Games Fund) and plan a Kickstarter."),
        ("Serious games that train nurses in triage, built together with a hospital.", "Validate with hospitals and learn about B2B sales cycles."),
        ("A Discord bot that runs tabletop RPG campaigns with AI-generated maps.", "Choose a business model and protect our IP."),
        ("VR training simulations for forklift drivers in logistics warehouses.", "Find launching customers and price a pilot."),
    ],
    "Hotel": [
        ("A pop-up restaurant concept run by hospitality students in empty retail spaces.", "Work out the financials and find landlords willing to cooperate."),
        ("Software that predicts breakfast demand for hotels to cut food waste.", "Test the prediction model with two hotels."),
        ("A boutique bed & breakfast in a renovated farmhouse near Ulvenhout.", "Make a business plan for the bank and check zoning rules."),
        ("A concierge service for international students arriving in Breda.", "Find out what universities and students would pay for it."),
    ],
    "Facility": [
        ("Smart sensors that measure meeting-room occupancy and suggest office downsizing.", "Get help with hardware sourcing and finding pilot companies."),
        ("A cleaning company that uses only eco-certified products for student houses.", "Learn about hiring, insurance and scaling up."),
        ("A platform where companies rent out unused office space by the hour.", "Validate demand from freelancers in Breda."),
        ("Workplace wellbeing programmes combining plants, light and acoustics.", "Create a convincing sales pitch for facility managers."),
    ],
    "Built Environment": [
        ("Modular tiny houses for student housing that can be placed on temporary locations.", "Talk to municipalities and housing corporations; financing."),
        ("A 3D-scanning service that makes digital twins of old buildings for renovation.", "Choose a target market and set up partnerships with architects."),
        ("Green roof subscriptions for homeowners, including installation and maintenance.", "Calculate margins and find suppliers."),
        ("An app that helps residents give input on urban plans in their neighbourhood.", "Find a first municipality as launching customer."),
    ],
    "Logistics": [
        ("Cargo-bike last-mile delivery for shops in Breda city centre.", "Test pricing with ten shops and plan the first hires."),
        ("A marketplace that fills empty truck space on return trips for small shippers.", "Validate with transport companies and understand legal liabilities."),
        ("Reusable packaging pool for local webshops, collected by bike.", "Find webshops for a pilot and calculate the deposit model."),
        ("Route optimisation software for mobile hairdressers and home-care workers.", "Build an MVP and find paying beta users."),
    ],
    "Data Science & AI": [
        ("Computer vision that counts and classifies litter on beaches from drone images.", "Find funding and a first customer such as a municipality or NGO."),
        ("An AI assistant that helps small webshops write product descriptions in Dutch and English.", "Decide on pricing and handle GDPR properly."),
        ("Predictive maintenance for bicycle-sharing fleets using sensor data.", "Talk to fleet operators and validate the business case."),
        ("A dashboard that helps student associations analyse their membership and events data.", "Find out if associations would pay and what features matter."),
    ],
    "I am an employee": [
        ("A coaching practice for young professionals about career choices, next to my job at BUas.", "Understand rules for side businesses and set up my first offer."),
        ("A Breda food-walk company focusing on international cuisine.", "Test the concept with a few paid walks this spring."),
    ],
}

GRAD_TOPICS = [
    "Developing a go-to-market strategy for my company in the Belgian market.",
    "Designing and testing a subscription model to create recurring revenue.",
    "Validating a new product line with existing customers through experiments.",
    "Building a scalable operations plan for growth from 2 to 10 employees.",
    "Measuring the social impact of my company and translating it into a business case for investors.",
    "Creating a brand strategy to reach international customers.",
]

TAGS = ["social impact", "tech", "sustainability", "funding needed", "event alumni", "international", "pitch competition"]


def demo_answers(reg):
    """The same structure the public form stores, so staff pages show realistic answers."""
    s, st = reg.student, reg.startup
    yes_no = {True: "Yes", False: "No", None: "–"}
    sections = [
        ["About you", [["First name", s.first_name], ["Last name", s.last_name], ["Student number", s.student_number or "–"],
                       ["Email", s.email], ["Phone number", s.phone], ["Domain", s.domain.name], ["Study year", s.study_year.name]]],
        ["Your business", [["Describe your business (idea)", st.description],
                           ["Do you already have paying customers?", yes_no[st.has_paying_customers]],
                           ["Have you validated your idea in practice with your target customers?", yes_no[st.idea_validated]],
                           ["How can we help you? What are your goals for the coach track?", st.goals]]],
    ]
    track = getattr(reg, "graduation", None) if hasattr(reg, "graduation") else None
    if track:
        sections.append(["Graduating within your own company", [
            ["Do you have approval from your programme to graduate with your own company?", track.get_approval_display()],
            ["Graduation assignment topic", track.topic], ["Name of graduation supervisor", track.supervisor_name],
            ["Intended hand-in date of final product", track.hand_in_date.strftime("%-d %B %Y")]]])
    sections += [
        ["Your coach", [["Preferred coach", reg.preferred_coach.full_name if reg.preferred_coach else "No preference"]]],
        ["Finally", [["Comments / anything else we should know", reg.comments or "–"],
                     ["I have read the privacy statement and agree that BUSS stores and uses my data as described there.", "Yes"]]],
    ]
    return {"sections": sections, "contact": {"first_name": s.first_name, "last_name": s.last_name, "email": s.email},
            "differences_from_existing_student": [], "demo": True}


class Command(BaseCommand):
    help = "Create fake demo students, startups, registrations, activities and dev logins."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG and DEMO_MODE are off.")
        parser.add_argument("--reset", action="store_true", help="Remove all students, startups and logs first.")
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, **options):
        if not (settings.DEBUG or settings.DEMO_MODE or options["force"]):
            raise CommandError("Refusing to create demo data with DEBUG and DEMO_MODE off. Use --force if you are sure.")
        self.password = os.environ.get("DEMO_PASSWORD", "") or (DEV_PASSWORD if settings.DEBUG else "")
        if not self.password:
            raise CommandError("Set DEMO_PASSWORD: the development password is public and must not be used on a server.")
        if options["reset"]:
            self._reset()
        if Student.objects.exists():
            self.stdout.write("Students already exist; demo data not added again.")
            return
        call_command("seed_reference")
        self.rng = random.Random(options["seed"])
        self.fake = Faker(["nl_NL", "en_GB", "de_DE", "nl_BE"])
        self.fake.seed_instance(options["seed"])
        with transaction.atomic():
            self._create_users()
            self._create_records()
        self.stdout.write(self.style.SUCCESS(
            f"Demo data created: {Student.objects.count()} students, {Startup.objects.count()} startups, "
            f"{Registration.objects.count()} registrations. Logins: admin / coach first names"
            + (f", password '{DEV_PASSWORD}'." if self.password == DEV_PASSWORD else ", password from DEMO_PASSWORD.")
        ))

    def _reset(self):
        with transaction.atomic():
            for model in (OutgoingEmail, Notification, FollowUp, Activity, GraduationTrack, Registration, Founder,
                          Startup, ExportLog, ImportBatch, PrivacyAction, LogEntry):
                model.objects.all().delete()
            Student.objects.update(merged_into=None)
            Student.objects.all().delete()
        self.stdout.write("Removed all students, startups and logs.")

    # -- users ------------------------------------------------------------
    def _user(self, username, **fields):
        """Create the login, or reset its password when it already exists (e.g. after --reset)."""
        user, _created = User.objects.update_or_create(username=username, defaults={"is_active": True, **fields})
        user.set_password(self.password)
        user.save()
        return user

    def _create_users(self):
        admin_group = Group.objects.get(name="Admin")
        coach_group = Group.objects.get(name="Coach")
        admin = self._user("admin", email="admin@example.org", is_staff=True, is_superuser=True, first_name="BUSS", last_name="Admin")
        admin.groups.add(admin_group)
        for coach in Coach.objects.all():
            username = coach.first_name.lower()
            user = self._user(username, email=f"{username}@example.org", is_staff=True,
                              first_name=coach.first_name, last_name=coach.last_name)
            user.groups.add(coach_group)
            coach.user = user
            coach.email = user.email
            coach.save()
        # Shival also administers the app.
        Coach.objects.get(first_name="Shival").user.groups.add(admin_group)

    # -- records ----------------------------------------------------------
    def _create_records(self):
        rng, fake = self.rng, self.fake
        self.today = timezone.localdate()
        self.settings = AppSettings.load()
        self.privacy = PrivacyStatement.current()
        self.stages = {s.name: s for s in PipelineStage.objects.all()}
        self.coaches = list(Coach.objects.all())
        self.tags = [Tag.objects.get_or_create(name=t)[0] for t in TAGS]
        domains = list(Domain.objects.order_by("order"))
        years = list(StudyYear.objects.order_by("order"))
        grad_year = next(y for y in years if y.is_graduation_track)
        not_applicable = next(y for y in years if y.name == "Not applicable")
        used_numbers = set()
        idea_pool = {d: list(ideas) for d, ideas in IDEAS.items()}
        for ideas in idea_pool.values():
            rng.shuffle(ideas)

        students = []
        for i in range(44):
            domain = domains[i % len(domains)]
            if domain.is_employee:
                year = not_applicable
            else:
                year = years[(i // len(domains) + i) % len(years)]
            first, last = fake.first_name(), fake.last_name()
            number = ""
            if not (domain.is_employee and i % 2):
                while not number or number in used_numbers:
                    number = str(rng.randint(100000, 299999))
                used_numbers.add(number)
            student = Student.objects.create(
                first_name=first,
                last_name=last,
                student_number=number,
                email=f"{first}.{last}".lower().replace(" ", "").replace("'", "") + "@buas.example",
                phone=f"+31 6 00{rng.randint(100000, 999999)}",
                domain=domain,
                study_year=year,
            )
            students.append(student)

        # Make sure there are at least six graduation-track students across different domains.
        grad_students = [s for s in students if s.study_year == grad_year]
        for s in students:
            if len(grad_students) >= 6:
                break
            if s not in grad_students and not s.domain.is_employee and s.domain not in {g.domain for g in grad_students}:
                s.study_year = grad_year
                s.save()
                grad_students.append(s)

        # Registration dates: spread over the past 10 months, with the most recent ones
        # producing every intake state in the queue.
        offsets = sorted((rng.randint(0, 300) for _ in students), reverse=True)
        offsets[-8:] = [16, 13, 11, 9, 6, 3, 1, 0]
        for idx, (student, days_ago) in enumerate(zip(students, offsets)):
            submitted = self._at(self.today - timedelta(days=days_ago))
            ideas = idea_pool.get(student.domain.name) or [rng.choice(sum(IDEAS.values(), []))]
            description, goals = ideas[idx % len(ideas)]
            self._register(student, submitted, description, goals, recent=days_ago <= 16, waiting=days_ago in (16, 13, 6, 1, 0))

        # Duplicates: three students come back with a second idea (same student number).
        for student in rng.sample(students[:30], 3):
            first_reg = student.registrations.first()
            submitted = first_reg.submitted_at + timedelta(days=rng.randint(40, 90))
            if submitted.date() > self.today:
                submitted = self._at(self.today - timedelta(days=4))
            description, goals = rng.choice(sum(IDEAS.values(), []))
            self._register(student, submitted, description, goals, recent=False, waiting=False, duplicate=True)

        # Students exist since their first registration.
        for student in students:
            first = student.registrations.order_by("submitted_at").first()
            Student.objects.filter(pk=student.pk).update(created_at=first.submitted_at)

        # A startup with two founders.
        startup = Startup.objects.filter(stage__name="Coaching").first()
        if startup:
            co_founder = next(s for s in students if not s.startups.filter(pk=startup.pk).exists())
            Founder.objects.get_or_create(startup=startup, student=co_founder, defaults={"role": "Co-founder"})

    def _register(self, student, submitted, description, goals, *, recent, waiting, duplicate=False):
        rng = self.rng
        preferred = rng.choice(self.coaches + [None, None])
        stage = self.stages["Registered"]
        startup = Startup.objects.create(
            description=description,
            goals=goals,
            has_paying_customers=rng.random() < 0.3,
            idea_validated=rng.random() < 0.45,
            stage=stage,
        )
        Startup.objects.filter(pk=startup.pk).update(created_at=submitted)
        startup.created_at = submitted  # keep the instance in sync; later saves write it back
        Founder.objects.create(startup=startup, student=student, joined_on=submitted.date())
        deadline = add_working_days(submitted.date(), self.settings.intake_working_days)
        reg = Registration.objects.create(
            student=student,
            startup=startup,
            submitted_at=submitted,
            preferred_coach=preferred,
            comments=rng.choice(["", "", "I can only meet on Tuesdays and Thursdays.", "I am abroad for an exchange until February.", "My friend is also joining as co-founder."]),
            answers={},
            consent_at=submitted,
            privacy_statement=self.privacy,
            is_duplicate_student=duplicate,
            intake_deadline=deadline,
        )

        if student.on_graduation_track and not student.graduation_tracks.exists():
            approval = GraduationTrack.Approval.NOT_YET if rng.random() < 0.5 else GraduationTrack.Approval.YES
            hand_in = self.today + timedelta(days=rng.choice([12, 25, 40, 75, 120, 160]))
            GraduationTrack.objects.create(
                registration=reg, student=student, startup=startup, approval=approval,
                topic=rng.choice(GRAD_TOPICS), supervisor_name=self.fake.name(), hand_in_date=hand_in,
            )
            if approval == GraduationTrack.Approval.NOT_YET:
                FollowUp.objects.create(
                    student=student, startup=startup, due_date=add_working_days(submitted.date(), 5),
                    title=f"Check programme approval for {student.full_name}", auto_reason="graduation_approval_missing",
                )

        reg.answers = demo_answers(reg)
        reg.save(update_fields=["answers"])

        if waiting:
            return  # Stays in the intake queue.

        # Intake scheduled a few working days after registration; some miss the 10-day promise.
        sched_after = rng.choice([2, 3, 4, 5, 6, 8, 9, 12, 14])
        scheduled = add_working_days(submitted.date(), sched_after)
        if scheduled > self.today:
            scheduled = self.today
        reg.intake_scheduled_on = scheduled
        coach = self._pick_coach(student)
        held = add_working_days(scheduled, rng.randint(1, 5))
        if recent and held > self.today:
            reg.save()
            startup.stage = self.stages["Intake scheduled"]
            startup.assigned_coach = coach
            startup.save()
            return
        reg.intake_held_on = held
        reg.intake_coach = coach
        reg.save()

        startup.assigned_coach = coach
        startup.stage = self.stages[rng.choice(
            ["Intake done", "Coaching", "Coaching", "Coaching", "Registered at KvK", "Graduated (own company)", "Alumni", "Stopped"]
        )]
        if startup.stage.name == "Registered at KvK":
            startup.kvk_number = str(rng.randint(10000000, 99999999))
            startup.name = self.fake.company()
        startup.save()
        startup.tags.set(rng.sample(self.tags, rng.randint(0, 2)))

        author = coach.user
        Activity.objects.create(startup=startup, kind=Activity.Kind.INTAKE, date=held, author=author,
                                body="Intake chat: discussed the idea, ambitions and what support is needed.")
        # Some startups have had no activity for weeks (shows up on the dashboard).
        day = held
        for _ in range(rng.randint(0, 4)):
            day = day + timedelta(days=rng.randint(7, 30))
            if day > self.today:
                break
            kind = rng.choice([Activity.Kind.NOTE, Activity.Kind.MEETING, Activity.Kind.MEETING, Activity.Kind.EMAIL, Activity.Kind.EVENT, Activity.Kind.REFERRAL])
            body = {
                Activity.Kind.NOTE: "Worked on the value proposition canvas; next step is customer interviews.",
                Activity.Kind.MEETING: "Coaching session: reviewed progress, discussed pricing and next experiments.",
                Activity.Kind.EMAIL: "Sent template for the financial plan and a link to the KvK starters page.",
                Activity.Kind.EVENT: "Attended the BUSS pitch night.",
                Activity.Kind.REFERRAL: "Referred to the Rabobank starters desk for financing questions.",
            }[kind]
            act = Activity.objects.create(startup=startup, kind=kind, date=day, author=author, body=body)
            Activity.objects.filter(pk=act.pk).update(created_at=self._at(day))
        last = startup.activities.order_by("-date").first()
        Startup.objects.filter(pk=startup.pk).update(last_activity_at=self._at(last.date))

        if startup.stage.name == "Coaching" and rng.random() < 0.6:
            FollowUp.objects.create(
                startup=startup, assigned_to=author, created_by=author,
                due_date=self.today + timedelta(days=rng.randint(-3, 10)),
                title=rng.choice(["Check in after customer interviews", "Review financial plan", "Send pitch-training invite", "Follow up on KvK registration"]),
            )

    def _pick_coach(self, student):
        rng = self.rng
        candidates = self.coaches
        if student.on_graduation_track:
            candidates = [c for c in self.coaches if student.domain not in c.domains.all()]
        return rng.choice(candidates)

    def _at(self, day):
        hour = self.rng.randint(8, 22)
        return timezone.make_aware(datetime.combine(day, time(hour, self.rng.randint(0, 59))))
