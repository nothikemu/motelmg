"""Global search palette, keyboard shortcut help, booking conflict notice and
generic catalog record editor."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QVBoxLayout, QWidget)

from motelmg.ui.theme import theme
from motelmg.ui.widgets.common import Badge, label, set_icon
from motelmg.ui.widgets.dialogs import BaseDialog
from motelmg.ui.widgets.forms import FormGrid
from motelmg.ui.widgets.table import Column, DataTable

KIND_ICONS = {"guest": "user", "reservation": "book", "room": "bed", "payment": "card", "ticket": "tool"}
KIND_LABELS = {"guest": "Guests", "reservation": "Reservations", "room": "Rooms", "payment": "Payments",
               "ticket": "Maintenance"}


class SearchResultWidget(QWidget):
    def __init__(self, hit):
        super().__init__()
        self.setObjectName("Transparent")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(12)
        ic = QLabel()
        set_icon(ic, KIND_ICONS.get(hit.kind, "search"), "text_muted", 18)
        row.addWidget(ic)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(label(hit.title, "h3"))
        text.addWidget(label(hit.subtitle, "faint"))
        row.addLayout(text, 1)
        if hit.badge:
            row.addWidget(Badge(hit.badge, hit.tone, small=True))


class GlobalSearchDialog(QDialog):
    """Ctrl+K command palette: find any guest, reservation, room, payment or ticket."""

    def __init__(self, parent, app, text: str = ""):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Search")
        self.setModal(True)
        self.setMinimumSize(640, 480)
        self.setStyleSheet(f"QDialog {{ background: {theme().c['surface']}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)
        self.input = QLineEdit(text)
        self.input.setObjectName("BigSearch")
        self.input.setPlaceholderText("Search guests, reservations (R10023), rooms, receipts, tickets…")
        self.input.installEventFilter(self)
        layout.addWidget(self.input)
        self.results = QListWidget()
        self.results.setStyleSheet("QListWidget { border: none; }")
        self.results.itemActivated.connect(self._open)
        self.results.itemClicked.connect(self._open)
        layout.addWidget(self.results, 1)
        self.hint = label("Type at least 2 characters. ↑↓ to move, Enter to open, Esc to close.", "faint")
        layout.addWidget(self.hint)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._search)
        self.input.textChanged.connect(lambda *_: self.timer.start())
        if text:
            self._search()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                count = self.results.count()
                if count:
                    row = self.results.currentRow()
                    step = 1 if key == Qt.Key.Key_Down else -1
                    nxt = row + step
                    while 0 <= nxt < count and not (self.results.item(nxt).flags() & Qt.ItemFlag.ItemIsSelectable):
                        nxt += step
                    if 0 <= nxt < count:
                        self.results.setCurrentRow(nxt)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.results.currentItem()
                if item:
                    self._open(item)
                return True
        return False

    def _search(self) -> None:
        self.results.clear()
        hits = self.app.ctx.search.search(self.input.text())
        if not hits:
            if len(self.input.text().strip()) >= 2:
                item = QListWidgetItem("No matches found")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.results.addItem(item)
            return
        current_kind = None
        first = True
        for hit in hits:
            if hit.kind != current_kind:
                current_kind = hit.kind
                header = QListWidgetItem(KIND_LABELS.get(hit.kind, hit.kind).upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                font = header.font()
                font.setPointSizeF(8)
                font.setBold(True)
                header.setFont(font)
                self.results.addItem(header)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, hit)
            widget = SearchResultWidget(hit)
            item.setSizeHint(widget.sizeHint())
            self.results.addItem(item)
            self.results.setItemWidget(item, widget)
            if first:
                self.results.setCurrentItem(item)
                first = False

    def _open(self, item: QListWidgetItem) -> None:
        hit = item.data(Qt.ItemDataRole.UserRole)
        if not hit:
            return
        self.accept()
        self.app.actions.open_hit(hit)


SHORTCUTS = [
    ("Ctrl+K  or  Ctrl+F", "Search everything"), ("Ctrl+N", "New reservation"), ("Ctrl+Shift+N", "Walk-in"),
    ("Ctrl+G", "New guest"), ("Ctrl+1 … Ctrl+9", "Switch section"), ("F5", "Refresh current view"),
    ("Ctrl+L", "Lock the screen"), ("Ctrl+P", "Print / export current report"), ("F1", "Show this help"),
    ("Enter / double-click", "Open the selected row"), ("Esc", "Close a dialog"),
]


class ShortcutsDialog(BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, "Keyboard shortcuts", "Work faster at the front desk.", icon_name="keyboard",
                         width=480)
        self.banner.hide()
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        for i, (keys, what) in enumerate(SHORTCUTS):
            k = label(keys, "h3")
            grid.addWidget(k, i, 0)
            grid.addWidget(label(what, "muted"), i, 1)
        self.body.addLayout(grid)
        self.add_footer_button("Close", self.accept, "primary", default=True)


class ConflictsDialog(BaseDialog):
    def __init__(self, parent, app, room, rows):
        super().__init__(parent, "Booking conflicts", f"Room {room.number} has upcoming reservations that must move "
                         "to another room.", icon_name="alert", tone="red", width=640)
        self.app = app
        self.banner.hide()
        table = DataTable([
            Column("confirmation_no", "Reservation", width=110, bold=True), Column("guest_name", "Guest", stretch=True),
            Column("check_in_date", "Arrival", width=120), Column("check_out_date", "Departure", width=120),
        ], app.fmt, row_height=34)
        table.set_rows([{"id": r["id"], "confirmation_no": r["confirmation_no"], "guest_name": r["guest_name"],
                         "check_in_date": r["check_in_date"], "check_out_date": r["check_out_date"]} for r in rows])
        table.setMinimumHeight(180)
        table.activated.connect(lambda row: app.actions.transfer(row["id"], parent=self))
        self.body.addWidget(table)
        self.body.addWidget(label("Double-click a reservation to move it to another room now. Conflicts also stay "
                                  "listed under Alerts until resolved.", "faint", wrap=True))
        self.add_footer_button("Done", self.accept, "primary", default=True)


class RecordDialog(BaseDialog):
    """Generic small editor driven by a field list (used for the billing catalog)."""

    def __init__(self, parent, title: str, fields: list[tuple[str, str, QWidget, bool]], save: Callable[[dict], Any],
                 *, subtitle: str = "", values: dict | None = None, icon_name: str = "edit"):
        super().__init__(parent, title, subtitle, icon_name=icon_name, width=500)
        self.save_fn = save
        self.form = self.register_form(FormGrid(2))
        for key, text, widget, span2 in fields:
            self.form.add(key, text, widget, span=2 if span2 else 1)
        if values:
            self.form.set_values(values)
        self.body.addWidget(self.form)
        self.add_cancel()
        self.add_footer_button("Save", lambda: self.attempt(lambda: self.save_fn(self.form.values())), "primary",
                               default=True)


__all__ = ["GlobalSearchDialog", "ShortcutsDialog", "ConflictsDialog", "RecordDialog", "QFrame"]
