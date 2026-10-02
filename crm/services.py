"""Business logic shared by the public form, walk-ins and the Forms import."""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from siteconfig.models import AppSettings, PipelineStage

from .models import Founder, FollowUp, GraduationTrack, Registration, Startup, Student
from .workdays import add_working_days

YES_NO_TO_BOOL = {"yes": True, "no": False}


def resolve_merged(student):
    """Follow merge links to the surviving record."""
    seen = set()
    while student.merged_into_id and student.pk not in seen:
        seen.add(student.pk)
        student = student.merged_into
    return student


def find_existing_student(student_number, email):
    """Match on student number first, then on email (case-insensitive). Anonymised records never match."""
    candidates = Student.objects.filter(anonymised_at__isnull=True)
    match = None
    if student_number:
        match = candidates.filter(student_number=student_number).order_by("created_at").first()
    if match is None and email:
        match = candidates.filter(email__iexact=email).order_by("created_at").first()
    return resolve_merged(match) if match else None


def student_differences(student, data):
    """[(field label, on record, as submitted)] for a matched student."""
    pairs = [
        ("First name", student.first_name, data["first_name"]),
        ("Last name", student.last_name, data["last_name"]),
        ("Student number", student.student_number, data.get("student_number") or ""),
        ("Email", student.email, data["email"]),
        ("Phone", student.phone, data["phone"]),
        ("Domain", student.domain.name, data["domain"].name),
        ("Study year", student.study_year.name, data["study_year"].name),
    ]
    return [[label, old, new] for label, old, new in pairs if str(old).strip().lower() != str(new).strip().lower() and new]


@dataclass
class SubmissionResult:
    registration: Registration
    is_duplicate: bool


@transaction.atomic
def create_registration(data, *, summary, source=Registration.Source.FORM, created_by=None, submitted_at=None):
    """Store one registration from cleaned form data.

    A known student (same student number or email) is never rejected: the new idea is
    linked to the existing student and the registration is flagged so staff can check it.
    """
    submitted_at = submitted_at or timezone.now()
    settings = AppSettings.load()

    student = find_existing_student(data.get("student_number"), data["email"])
    is_duplicate = student is not None
    differences = []
    if student is None:
        student = Student.objects.create(
            first_name=data["first_name"],
            last_name=data["last_name"],
            student_number=data.get("student_number") or "",
            email=data["email"],
            phone=data["phone"],
            domain=data["domain"],
            study_year=data["study_year"],
        )
    else:
        # Never overwrite the existing record automatically: a mistyped student number would
        # otherwise change someone else's details. Staff see the differences and decide.
        differences = student_differences(student, data)
        if not student.student_number and data.get("student_number"):
            student.student_number = data["student_number"]
        student.archived_at = None
        student.save()

    startup = Startup.objects.create(
        description=data["description"],
        has_paying_customers=YES_NO_TO_BOOL.get(data.get("has_paying_customers")),
        idea_validated=YES_NO_TO_BOOL.get(data.get("idea_validated")),
        goals=data["goals"],
        stage=PipelineStage.initial(),
    )
    Founder.objects.create(startup=startup, student=student, joined_on=timezone.localdate(submitted_at))

    registration = Registration.objects.create(
        student=student,
        startup=startup,
        submitted_at=submitted_at,
        source=source,
        preferred_coach=data.get("preferred_coach"),
        comments=data.get("comments", ""),
        answers={
            "sections": summary,
            # What was typed in, which may differ from the matched student record.
            "contact": {"first_name": data["first_name"], "last_name": data["last_name"], "email": data["email"]},
            "differences_from_existing_student": differences,
        },
        consent_at=submitted_at if data.get("privacy_consent") else None,
        privacy_statement=data.get("privacy_version"),
        is_duplicate_student=is_duplicate,
        created_by=created_by,
        intake_deadline=add_working_days(timezone.localdate(submitted_at), settings.intake_working_days),
    )

    if data["study_year"].is_graduation_track and data.get("grad_approval"):
        track = GraduationTrack.objects.create(
            registration=registration,
            student=student,
            startup=startup,
            approval=data["grad_approval"],
            topic=data["grad_topic"],
            supervisor_name=data["grad_supervisor"],
            hand_in_date=data["grad_hand_in_date"],
        )
        if track.approval_missing:
            FollowUp.objects.create(
                student=student,
                startup=startup,
                title=f"Check programme approval for {student.full_name}",
                notes="Student registered for graduating within own company without programme approval yet.",
                due_date=add_working_days(timezone.localdate(submitted_at), 5),
                auto_reason="graduation_approval_missing",
            )

    return SubmissionResult(registration=registration, is_duplicate=is_duplicate)
