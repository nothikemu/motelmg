"""Type-ahead guest selector with a 'new guest' shortcut."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QStackedWidget, QVBoxLayout, QWidget)

from motelmg.ui.widgets.common import Avatar, Badge, button, clear_layout, label, set_icon


class GuestPicker(QWidget):
    changed = Signal(object)  # guest id or None

    def __init__(self, app, guest_id: int | None = None, *, allow_change: bool = True):
        super().__init__()
        self.setObjectName("Transparent")
        self.app = app
        self.guest_id: int | None = None
        self.allow_change = allow_change
        self.stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        # search page
        search_page = QWidget()
        search_page.setObjectName("Transparent")
        sl = QVBoxLayout(search_page)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search guests by name, phone, email or ID…")
        self.search.setClearButtonEnabled(True)
        self.search.installEventFilter(self)
        row.addWidget(self.search, 1)
        self.new_btn = button("New guest", "user-plus", "soft", on_click=self._new_guest)
        self.new_btn.setEnabled(app.ctx.can("guests.edit"))
        row.addWidget(self.new_btn)
        sl.addLayout(row)
        self.results = QListWidget()
        self.results.setMaximumHeight(190)
        self.results.hide()
        self.results.itemActivated.connect(self._pick_item)
        self.results.itemClicked.connect(self._pick_item)
        sl.addWidget(self.results)
        self.hint = label("Start typing to find a returning guest, or create a new profile.", "faint")
        sl.addWidget(self.hint)
        self.stack.addWidget(search_page)

        # selected page
        self.card = QFrame()
        self.card.setProperty("soft", True)
        cl = QHBoxLayout(self.card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(12)
        self.avatar = Avatar("", 40)
        cl.addWidget(self.avatar)
        info = QVBoxLayout()
        info.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name = label("", "h3")
        top.addWidget(self.name)
        self.badges = QHBoxLayout()
        self.badges.setSpacing(4)
        top.addLayout(self.badges)
        top.addStretch(1)
        info.addLayout(top)
        self.details = label("", "muted", wrap=True)
        info.addWidget(self.details)
        self.warning = label("", "error", wrap=True)
        info.addWidget(self.warning)
        cl.addLayout(info, 1)
        self.view_btn = button("Profile", "user", "ghost", small=True, on_click=self._open_profile)
        self.change_btn = button("Change", "transfer", "ghost", small=True, on_click=self.clear)
        cl.addWidget(self.view_btn, 0, Qt.AlignmentFlag.AlignTop)
        cl.addWidget(self.change_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.change_btn.setVisible(allow_change)
        self.stack.addWidget(self.card)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda *_: self._timer.start())
        if guest_id:
            self.set_guest(guest_id)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down and self.results.isVisible() and self.results.count():
                self.results.setFocus()
                self.results.setCurrentRow(0)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.results.count() == 1:
                self._pick_item(self.results.item(0))
                return True
        return False

    def _run_search(self) -> None:
        text = self.search.text().strip()
        self.results.clear()
        if len(text) < 2:
            self.results.hide()
            self.hint.show()
            return
        guests = self.app.ctx.repo_guests.search(text, limit=25)
        for g in guests:
            parts = [g.phone, g.email, g.city]
            tag = " · DO NOT RENT" if g.is_banned else (" · VIP" if g.is_vip else "")
            item = QListWidgetItem(f"{g.full_name}{tag}\n{' · '.join(p for p in parts if p) or 'No contact info'}"
                                   f"   ·   {g.stays} stay(s)")
            item.setData(Qt.ItemDataRole.UserRole, g.id)
            self.results.addItem(item)
        if not guests:
            item = QListWidgetItem("No matching guests — click 'New guest' to create one")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(item)
        self.results.show()
        self.hint.hide()

    def _pick_item(self, item: QListWidgetItem) -> None:
        guest_id = item.data(Qt.ItemDataRole.UserRole)
        if guest_id:
            self.set_guest(guest_id)

    def set_guest(self, guest_id: int | None) -> None:
        self.guest_id = guest_id
        if guest_id is None:
            self.stack.setCurrentIndex(0)
            self.search.setFocus()
            self.changed.emit(None)
            return
        guest = self.app.ctx.guests.get(guest_id)
        self.avatar.set_name(guest.full_name)
        self.name.setText(guest.full_name)
        clear_layout(self.badges)
        if guest.is_vip:
            self.badges.addWidget(Badge("VIP", "amber", small=True))
        if guest.in_house:
            self.badges.addWidget(Badge("In house", "blue", small=True))
        if guest.stays:
            self.badges.addWidget(Badge(f"{guest.stays} stay{'s' if guest.stays != 1 else ''}", "gray", small=True))
        self.details.setText(" · ".join(x for x in (guest.phone, guest.email, guest.id_number and
                                                          f"ID {guest.id_number}") if x) or "No contact details")
        warnings = []
        if guest.is_banned:
            warnings.append(f"DO NOT RENT: {guest.banned_reason or 'flagged by management'}")
        for note in self.app.ctx.notes.important_for_guest(guest.id)[:2]:
            warnings.append(f"⚠ {note.body}")
        self.warning.setText("\n".join(warnings))
        self.warning.setVisible(bool(warnings))
        self.stack.setCurrentIndex(1)
        self.changed.emit(guest_id)

    def clear(self) -> None:
        self.search.clear()
        self.set_guest(None)

    def _new_guest(self) -> None:
        from motelmg.ui.dialogs.guest import GuestDialog
        text = self.search.text().strip()
        prefill = {}
        if text and not any(ch.isdigit() for ch in text) and "@" not in text:
            parts = text.split()
            prefill = {"first_name": parts[0].title(), "last_name": " ".join(parts[1:]).title()}
        dlg = GuestDialog(self, self.app, prefill=prefill)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_value:
            self.set_guest(dlg.result_value)

    def _open_profile(self) -> None:
        if self.guest_id:
            self.app.actions.open_guest(self.guest_id, parent=self)
            self.set_guest(self.guest_id)


__all__ = ["GuestPicker", "set_icon"]
