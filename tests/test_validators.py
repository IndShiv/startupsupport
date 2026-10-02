import pytest
from django.core.exceptions import ValidationError

from crm.validators import MaxWordsValidator, count_words, normalise_phone, validate_phone, validate_student_number


@pytest.mark.parametrize("value", ["123456", "000001", ""])
def test_valid_student_numbers(value):
    validate_student_number(value)


@pytest.mark.parametrize("value", ["12345", "1234567", "12345a", " 123456", "u123456"])
def test_invalid_student_numbers(value):
    with pytest.raises(ValidationError):
        validate_student_number(value)


@pytest.mark.parametrize("value", ["+31 6 12345678", "0612345678", "06-12345678", "+32 470 12 34 56", "+49 (0)30 1234567", "0031612345678"])
def test_valid_phone_numbers(value):
    validate_phone(value)


@pytest.mark.parametrize("value", ["12345", "phone me", "+31 6 1234 5678 9012 34", "06/12345678"])
def test_invalid_phone_numbers(value):
    with pytest.raises(ValidationError):
        validate_phone(value)


def test_normalise_phone():
    assert normalise_phone("06 1234 5678") == "0612345678"
    assert normalise_phone("0031 6 12345678") == "+31612345678"
    assert normalise_phone("+31 (0)6-12345678") == "+310612345678"


def test_word_limit():
    validator = MaxWordsValidator(5)
    validator("one two three four five")
    with pytest.raises(ValidationError) as exc:
        validator("one two three four five six")
    assert "at most 5 words" in str(exc.value)
    assert count_words("  spaced   out\nwords ") == 3
