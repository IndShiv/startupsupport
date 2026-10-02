import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

STUDENT_NUMBER_RE = re.compile(r"^\d{6}$")
PHONE_ALLOWED_RE = re.compile(r"^\+?[\d\s().-]+$")


def validate_student_number(value):
    if value and not STUDENT_NUMBER_RE.match(value):
        raise ValidationError(_("A student number is exactly 6 digits, e.g. 123456."), code="student_number")


def normalise_phone(value):
    """Strip spacing/punctuation, keep a leading '+'. '06 1234 5678' -> '0612345678'."""
    value = (value or "").strip()
    if value.startswith("00"):
        value = "+" + value[2:]
    plus = value.startswith("+")
    digits = re.sub(r"\D", "", value)
    return ("+" if plus else "") + digits


def validate_phone(value):
    if not value:
        return
    if not PHONE_ALLOWED_RE.match(value.strip()):
        raise ValidationError(_("Use digits only, optionally starting with + and a country code, e.g. +31 6 12345678."), code="phone")
    digits = re.sub(r"\D", "", value)
    if not 9 <= len(digits) <= 15:
        raise ValidationError(_("This phone number has too few or too many digits."), code="phone_length")


def count_words(text):
    return len((text or "").split())


class MaxWordsValidator:
    def __init__(self, limit):
        self.limit = limit

    def __call__(self, value):
        words = count_words(value)
        if words > self.limit:
            raise ValidationError(
                _("Please use at most %(limit)d words (you used %(words)d)."),
                code="max_words",
                params={"limit": self.limit, "words": words},
            )

    def __eq__(self, other):
        return isinstance(other, MaxWordsValidator) and other.limit == self.limit

    def deconstruct(self):
        return ("crm.validators.MaxWordsValidator", (self.limit,), {})
