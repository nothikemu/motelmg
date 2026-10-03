"""Display formatting that honours the user's regional settings."""

from __future__ import annotations

from datetime import date, datetime, time

from PySide6.QtCore import QDate, QDateTime, QTime


class Formatter:
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def date_format(self) -> str:
        return self.ctx.settings.get_str("app.date_format") or "MMM d, yyyy"

    @property
    def time_format(self) -> str:
        return self.ctx.settings.get_str("app.time_format") or "h:mm AP"

    def money(self, cents: int | None, **kwargs) -> str:
        return self.ctx.settings.money(cents, **kwargs)

    def date(self, d: date | None) -> str:
        if not d:
            return ""
        if not isinstance(d, date):
            return str(d)
        if isinstance(d, datetime):
            d = d.date()
        return QDate(d.year, d.month, d.day).toString(self.date_format)

    def short_date(self, d: date | None) -> str:
        if not d:
            return ""
        if not isinstance(d, date):
            return str(d)
        return QDate(d.year, d.month, d.day).toString("ddd, MMM d")

    def time(self, t: time | str | None) -> str:
        if not t:
            return ""
        if isinstance(t, str):
            try:
                t = datetime.strptime(t, "%H:%M").time()
            except ValueError:
                return t
        return QTime(t.hour, t.minute).toString(self.time_format)

    def datetime(self, dt: datetime | None) -> str:
        if not dt:
            return ""
        if not isinstance(dt, datetime):
            return self.date(dt) if isinstance(dt, date) else str(dt)
        qdt = QDateTime(QDate(dt.year, dt.month, dt.day), QTime(dt.hour, dt.minute, dt.second))
        return qdt.toString(f"{self.date_format} {self.time_format}")

    def relative_day(self, d: date | None) -> str:
        if not d:
            return ""
        today = self.ctx.clock.today()
        delta = (d - today).days
        if delta == 0:
            return "Today"
        if delta == 1:
            return "Tomorrow"
        if delta == -1:
            return "Yesterday"
        return self.short_date(d)

    def value(self, value, kind: str) -> str:
        """Generic formatter used by report tables and exports."""
        if value is None or value == "":
            return ""
        if kind == "money" and isinstance(value, int):
            return self.money(value)
        if kind == "percent" and isinstance(value, (int, float)):
            return f"{value:.1f}%"
        if kind == "float" and isinstance(value, (int, float)):
            return f"{value:.1f}"
        if isinstance(value, datetime):
            return self.datetime(value)
        if isinstance(value, date):
            return self.date(value)
        if kind == "int" and isinstance(value, (int, float)):
            return f"{int(value):,}"
        return str(value)
