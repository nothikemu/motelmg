"""Reusable input validation helpers used by the service layer."""

from __future__ import annotations

import re

from motelmg.core.errors import ValidationError

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^[0-9+()\-.\s/x]{5,30}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
ROOM_NUMBER_RE = re.compile(r"^[A-Za-z0-9-]{1,10}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,12}$")


def clean(value: object) -> str:
    """Normalise a free text value: ``None`` -> ``""`` and strip whitespace."""
    if value is None:
        return ""
    return " ".join(str(value).split()) if "\n" not in str(value) else str(value).strip()


def required(value: object, label: str, field: str | None = None, *, max_len: int = 200) -> str:
    text = clean(value)
    if not text:
        raise ValidationError(f"{label} is required.", field=field)
    if len(text) > max_len:
        raise ValidationError(f"{label} must be at most {max_len} characters.", field=field)
    return text


def optional(value: object, label: str, field: str | None = None, *, max_len: int = 500) -> str:
    text = clean(value)
    if len(text) > max_len:
        raise ValidationError(f"{label} must be at most {max_len} characters.", field=field)
    return text


def email(value: object, field: str = "email", *, required_: bool = False) -> str:
    text = clean(value)
    if not text:
        if required_:
            raise ValidationError("Email is required.", field=field)
        return ""
    if len(text) > 254 or not EMAIL_RE.match(text):
        raise ValidationError("Enter a valid email address (e.g. name@example.com).", field=field)
    return text.lower()


def phone(value: object, field: str = "phone", *, required_: bool = False) -> str:
    text = clean(value)
    if not text:
        if required_:
            raise ValidationError("Phone number is required.", field=field)
        return ""
    digits = re.sub(r"\D", "", text)
    if not PHONE_RE.match(text) or len(digits) < 5:
        raise ValidationError("Enter a valid phone number.", field=field)
    return text


def int_range(value: object, label: str, field: str | None, lo: int, hi: int) -> int:
    try:
        number = int(str(value).strip()) if not isinstance(value, int) else value
    except (TypeError, ValueError):
        raise ValidationError(f"{label} must be a whole number.", field=field) from None
    if number < lo or number > hi:
        raise ValidationError(f"{label} must be between {lo} and {hi}.", field=field)
    return number


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")
