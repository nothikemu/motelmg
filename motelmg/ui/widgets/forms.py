"""Form building blocks with inline validation messages."""

from __future__ import annotations

from datetime import date, time
from typing import Any, Callable

from PySide6.QtCore import QDate, QRegularExpression, Qt, QTime, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QSpinBox, QTimeEdit, QToolButton, QVBoxLayout, QWidget)

from motelmg.ui.widgets.common import label, set_icon, set_prop

DATE_DISPLAY = "MMM d, yyyy"


def qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def pydate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


class MoneyEdit(QLineEdit):
    def __init__(self, cents: int | None = None, *, allow_negative: bool = False, placeholder: str = "0.00"):
        super().__init__()
        pattern = r"^-?\d{0,9}([.,]\d{0,2})?$" if allow_negative else r"^\d{0,9}([.,]\d{0,2})?$"
        self.setValidator(QRegularExpressionValidator(QRegularExpression(pattern), self))
        self.setPlaceholderText(placeholder)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setMaximumWidth(180)
        if cents is not None:
            self.set_cents(cents)

    def set_cents(self, cents: int | None) -> None:
        self.setText("" if cents is None else f"{cents / 100:.2f}")

    def value(self) -> str:
        return self.text().replace(",", ".").strip()

    def cents(self) -> int:
        try:
            return int(round(float(self.value() or 0) * 100))
        except ValueError:
            return 0


class DateEdit(QDateEdit):
    def __init__(self, value: date | None = None, *, minimum: date | None = None):
        super().__init__()
        self.setCalendarPopup(True)
        self.setDisplayFormat(DATE_DISPLAY)
        if minimum:
            self.setMinimumDate(qdate(minimum))
        self.setDate(qdate(value or date.today()))
        self.setMinimumWidth(140)

    def value(self) -> date:
        return pydate(self.date())

    def set_value(self, value: date) -> None:
        self.setDate(qdate(value))


class OptionalDateEdit(QWidget):
    """Date that may be empty: shows 'Not set' until the user picks one."""

    changed = Signal()

    def __init__(self, value: date | None = None):
        super().__init__()
        self.setObjectName("Transparent")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.edit = QDateEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat(DATE_DISPLAY)
        self.edit.setMinimumDate(QDate(1900, 1, 1))
        self.edit.setSpecialValueText("Not set")
        self.edit.setMinimumWidth(140)
        self.clear_btn = QToolButton()
        self.clear_btn.setToolTip("Clear date")
        set_icon(self.clear_btn, "x", "text_faint", 13)
        self.clear_btn.clicked.connect(lambda: self.set_value(None))
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.clear_btn)
        self.edit.dateChanged.connect(lambda *_: self.changed.emit())
        self.set_value(value)

    def set_value(self, value: date | None) -> None:
        if value is None:
            self.edit.setDate(self.edit.minimumDate())
        else:
            self.edit.setDate(qdate(value))

    def value(self) -> date | None:
        q = self.edit.date()
        if q == self.edit.minimumDate():
            return None
        return pydate(q)

    def setFocus(self) -> None:  # noqa: N802
        self.edit.setFocus()


class TimeEdit(QTimeEdit):
    def __init__(self, value: time | str | None = None):
        super().__init__()
        self.setDisplayFormat("h:mm AP")
        self.set_value(value)

    def set_value(self, value: time | str | None) -> None:
        if isinstance(value, str) and value:
            hh, mm = value.split(":")[:2]
            value = time(int(hh), int(mm))
        if isinstance(value, time):
            self.setTime(QTime(value.hour, value.minute))

    def value(self) -> str:
        return self.time().toString("HH:mm")


class OptionalTimeEdit(QWidget):
    def __init__(self, value: str = "", placeholder: str = "Any time"):
        super().__init__()
        self.setObjectName("Transparent")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.check = QCheckBox()
        self.edit = TimeEdit("15:00")
        self.placeholder = placeholder
        layout.addWidget(self.check)
        layout.addWidget(self.edit, 1)
        self.check.toggled.connect(self.edit.setEnabled)
        self.set_value(value)

    def set_value(self, value: str) -> None:
        self.check.setChecked(bool(value))
        self.edit.setEnabled(bool(value))
        if value:
            self.edit.set_value(value)

    def value(self) -> str:
        return self.edit.value() if self.check.isChecked() else ""


def combo(items: list[tuple[str, Any]], current: Any = None, *, editable: bool = False) -> QComboBox:
    box = QComboBox()
    box.setEditable(editable)
    for text, data in items:
        box.addItem(text, data)
    if current is not None:
        set_combo(box, current)
    box.setMinimumWidth(120)
    return box


def set_combo(box: QComboBox, data: Any) -> None:
    for i in range(box.count()):
        if box.itemData(i) == data:
            box.setCurrentIndex(i)
            return


def spin(value: int = 0, lo: int = 0, hi: int = 99, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(lo, hi)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    box.setMinimumWidth(80)
    return box


def text_area(text: str = "", placeholder: str = "", height: int = 70) -> QPlainTextEdit:
    edit = QPlainTextEdit(text)
    edit.setPlaceholderText(placeholder)
    edit.setFixedHeight(height)
    edit.setTabChangesFocus(True)
    return edit


def line(text: str = "", placeholder: str = "", max_len: int = 200) -> QLineEdit:
    edit = QLineEdit(text or "")
    edit.setPlaceholderText(placeholder)
    edit.setMaxLength(max_len)
    return edit


def widget_value(widget: QWidget) -> Any:
    if isinstance(widget, MoneyEdit):
        return widget.value()
    if isinstance(widget, (DateEdit, OptionalDateEdit, TimeEdit, OptionalTimeEdit)):
        return widget.value()
    if isinstance(widget, QLineEdit):
        return widget.text().strip()
    if isinstance(widget, QPlainTextEdit):
        return widget.toPlainText().strip()
    if isinstance(widget, QComboBox):
        return widget.currentData()
    if isinstance(widget, QSpinBox):
        return widget.value()
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    return None


def set_widget_value(widget: QWidget, value: Any) -> None:
    if isinstance(widget, MoneyEdit):
        widget.set_cents(value)
    elif isinstance(widget, (DateEdit, OptionalDateEdit, TimeEdit, OptionalTimeEdit)):
        widget.set_value(value)
    elif isinstance(widget, QLineEdit):
        widget.setText("" if value is None else str(value))
    elif isinstance(widget, QPlainTextEdit):
        widget.setPlainText(value or "")
    elif isinstance(widget, QComboBox):
        set_combo(widget, value)
    elif isinstance(widget, QSpinBox):
        widget.setValue(int(value or 0))
    elif isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))


class FormGrid(QWidget):
    """Responsive grid of labelled fields with per-field error messages.

    Fields are laid out in ``columns`` columns; a field can span several.
    """

    def __init__(self, columns: int = 2):
        super().__init__()
        self.setObjectName("Transparent")
        self.columns = columns
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(4)
        for c in range(columns):
            self.grid.setColumnStretch(c, 1)
        self.fields: dict[str, QWidget] = {}
        self.errors: dict[str, QLabel] = {}
        self.labels: dict[str, QLabel] = {}
        self._row = 0
        self._col = 0

    def add(self, key: str, title: str, widget: QWidget, *, required: bool = False, span: int = 1,
            hint: str = "", new_row: bool = False) -> QWidget:
        if new_row and self._col:
            self._row += 3
            self._col = 0
        if self._col + span > self.columns:
            self._row += 3
            self._col = 0
        title_lbl = label(title + (" *" if required else ""), "label")
        self.grid.addWidget(title_lbl, self._row, self._col, 1, span)
        self.grid.addWidget(widget, self._row + 1, self._col, 1, span)
        err = label(hint, "faint" if hint else "error", wrap=True)
        err.setProperty("hint", hint)
        err.setVisible(bool(hint))
        self.grid.addWidget(err, self._row + 2, self._col, 1, span)
        self.fields[key] = widget
        self.errors[key] = err
        self.labels[key] = title_lbl
        self._col += span
        if self._col >= self.columns:
            self._row += 3
            self._col = 0
        return widget

    def add_widget(self, widget: QWidget, span: int | None = None) -> None:
        if self._col:
            self._row += 3
            self._col = 0
        self.grid.addWidget(widget, self._row, 0, 1, span or self.columns)
        self._row += 3

    def values(self) -> dict[str, Any]:
        return {key: widget_value(w) for key, w in self.fields.items() if not isinstance(w, QLabel)}

    def set_values(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in self.fields:
                set_widget_value(self.fields[key], value)

    def clear_errors(self) -> None:
        for key, err in self.errors.items():
            hint = err.property("hint") or ""
            err.setText(hint)
            err.setProperty("role", "faint" if hint else "error")
            set_prop(err, "role", "faint" if hint else "error")
            err.setVisible(bool(hint))
            self._mark(self.fields[key], False)

    def set_errors(self, errors: dict[str, str]) -> bool:
        """Show messages for known fields. Returns True if any field matched."""
        matched = False
        first: QWidget | None = None
        for key, message in errors.items():
            if key not in self.fields:
                continue
            matched = True
            err = self.errors[key]
            err.setText(message)
            set_prop(err, "role", "error")
            err.setVisible(True)
            self._mark(self.fields[key], True)
            first = first or self.fields[key]
        if first is not None:
            first.setFocus()
        return matched

    @staticmethod
    def _mark(widget: QWidget, invalid: bool) -> None:
        target = widget.edit if isinstance(widget, OptionalDateEdit) else widget
        set_prop(target, "invalid", invalid)

    def set_visible(self, key: str, visible: bool) -> None:
        self.fields[key].setVisible(visible)
        self.labels[key].setVisible(visible)
        if not visible:
            self.errors[key].setVisible(False)


def on_change(widget: QWidget, callback: Callable[[], None]) -> None:
    """Connect the natural 'value changed' signal of any input widget."""
    if isinstance(widget, OptionalDateEdit):
        widget.changed.connect(callback)
    elif isinstance(widget, QDateEdit):
        widget.dateChanged.connect(lambda *_: callback())
    elif isinstance(widget, QLineEdit):
        widget.textChanged.connect(lambda *_: callback())
    elif isinstance(widget, QComboBox):
        widget.currentIndexChanged.connect(lambda *_: callback())
    elif isinstance(widget, QSpinBox):
        widget.valueChanged.connect(lambda *_: callback())
    elif isinstance(widget, QCheckBox):
        widget.toggled.connect(lambda *_: callback())
    elif isinstance(widget, QPlainTextEdit):
        widget.textChanged.connect(callback)


__all__ = ["FormGrid", "MoneyEdit", "DateEdit", "OptionalDateEdit", "TimeEdit", "OptionalTimeEdit", "combo",
           "set_combo", "spin", "text_area", "line", "on_change", "qdate", "pydate", "QVBoxLayout"]
