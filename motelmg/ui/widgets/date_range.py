"""Date range picker with common presets."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from motelmg.core.dates import add_months, month_bounds
from motelmg.ui.widgets.common import label
from motelmg.ui.widgets.forms import DateEdit, combo, set_combo

PRESETS = [
    ("Today", "today"), ("Yesterday", "yesterday"), ("Last 7 days", "7d"), ("Last 30 days", "30d"),
    ("This month", "month"), ("Last month", "last_month"), ("This year", "year"), ("Next 7 days", "next7"),
    ("Next 30 days", "next30"), ("Custom range", "custom"),
]


def preset_range(key: str, today: date) -> tuple[date, date]:
    if key == "today":
        return today, today
    if key == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    if key == "7d":
        return today - timedelta(days=6), today
    if key == "30d":
        return today - timedelta(days=29), today
    if key == "month":
        return today.replace(day=1), today
    if key == "last_month":
        first = add_months(today.replace(day=1), -1)
        return month_bounds(first.year, first.month)
    if key == "year":
        return date(today.year, 1, 1), today
    if key == "next7":
        return today, today + timedelta(days=6)
    if key == "next30":
        return today, today + timedelta(days=29)
    return today, today


class DateRangePicker(QWidget):
    changed = Signal(object, object)

    def __init__(self, today: date, preset: str = "30d", presets: list[tuple[str, str]] | None = None):
        super().__init__()
        self.setObjectName("Transparent")
        self.today = today
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.preset = combo(presets or PRESETS, preset)
        self.preset.setMinimumWidth(140)
        self.start = DateEdit(today)
        self.end = DateEdit(today)
        layout.addWidget(self.preset)
        layout.addWidget(self.start)
        layout.addWidget(label("to", "muted"))
        layout.addWidget(self.end)
        layout.addStretch(1)
        self._updating = False
        self._apply_preset()
        self.preset.currentIndexChanged.connect(lambda *_: self._apply_preset(emit=True))
        self.start.dateChanged.connect(lambda *_: self._manual())
        self.end.dateChanged.connect(lambda *_: self._manual())
        self._updating = False

    def _apply_preset(self, emit: bool = False) -> None:
        key = self.preset.currentData()
        if key == "custom":
            return
        self._updating = True
        start, end = preset_range(key, self.today)
        self.start.set_value(start)
        self.end.set_value(end)
        self._updating = False
        if emit:
            self.changed.emit(start, end)

    def _manual(self) -> None:
        if getattr(self, "_updating", False):
            return
        if self.end.value() < self.start.value():
            self._updating = True
            self.end.set_value(self.start.value())
            self._updating = False
        set_combo(self.preset, "custom")
        self.changed.emit(*self.value())

    def value(self) -> tuple[date, date]:
        return self.start.value(), self.end.value()
