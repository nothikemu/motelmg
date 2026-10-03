"""Date/time helpers.

Dates are stored in the database as ISO strings (``YYYY-MM-DD``) and
timestamps as local time ``YYYY-MM-DD HH:MM:SS``. A motel operates in a single
timezone, so naive local timestamps are appropriate and easy to read.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterator

from motelmg.core.errors import ValidationError

ISO_DATE = "%Y-%m-%d"
ISO_DATETIME = "%Y-%m-%d %H:%M:%S"


class Clock:
    """Source of the current time. Tests replace it with a fixed clock."""

    def __init__(self, fixed: datetime | None = None):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed if self._fixed is not None else datetime.now().replace(microsecond=0)

    def today(self) -> date:
        return self.now().date()

    def set(self, value: datetime | None) -> None:
        self._fixed = value

    def advance(self, **kwargs) -> None:
        self._fixed = self.now() + timedelta(**kwargs)


def to_iso(d: date | None) -> str | None:
    return d.strftime(ISO_DATE) if d else None


def to_iso_dt(dt: datetime | None) -> str | None:
    return dt.strftime(ISO_DATETIME) if dt else None


def parse_date(value: object, *, field: str | None = None, label: str = "Date") -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{label} is required.", field=field)
    try:
        return datetime.strptime(text[:10], ISO_DATE).date()
    except ValueError:
        raise ValidationError(f"{label} is not a valid date.", field=field) from None


def parse_optional_date(value: object, *, field: str | None = None, label: str = "Date") -> date | None:
    if value in (None, ""):
        return None
    return parse_date(value, field=field, label=label)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], ISO_DATETIME)
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def parse_time(value: object, *, field: str | None = None, label: str = "Time") -> time:
    if isinstance(value, time):
        return value
    text = str(value or "").strip().upper()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValidationError(f"{label} is not a valid time (use HH:MM).", field=field)


def time_to_str(t: time) -> str:
    return t.strftime("%H:%M")


def nights_between(check_in: date, check_out: date) -> int:
    return (check_out - check_in).days


def iter_nights(check_in: date, check_out: date) -> Iterator[date]:
    current = check_in
    while current < check_out:
        yield current
        current += timedelta(days=1)


def iter_days(start: date, end_inclusive: date) -> Iterator[date]:
    current = start
    while current <= end_inclusive:
        yield current
        current += timedelta(days=1)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    nxt = date(year + (month // 12), (month % 12) + 1, 1)
    return first, nxt - timedelta(days=1)


def add_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last_day = month_bounds(year, month)[1].day
    return date(year, month, min(d.day, last_day))
