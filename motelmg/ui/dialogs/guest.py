"""Guest profile: create/edit form, stay history and notes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from motelmg.core.enums import IdType, ReservationStatus
from motelmg.models import Guest
from motelmg.ui.widgets.common import Avatar, Badge, Card, label
from motelmg.ui.widgets.dialogs import BaseDialog, confirm, guarded
from motelmg.ui.widgets.forms import FormGrid, OptionalDateEdit, combo, line, text_area
from motelmg.ui.widgets.notes import NotesPanel
from motelmg.ui.widgets.table import Column, DataTable


def guest_form(guest: Guest | None = None, *, compact: bool = False) -> FormGrid:
    form = FormGrid(2)
    form.add("first_name", "First name", line(max_len=60), required=True)
    form.add("last_name", "Last name", line(max_len=60), required=True)
    form.add("phone", "Phone", line(placeholder="(555) 123-4567", max_len=30))
    form.add("email", "Email", line(placeholder="name@example.com", max_len=254))
    form.add("id_type", "ID type", combo([("— None —", "")] + [(v, k) for k, v in IdType.LABELS.items()]))
    form.add("id_number", "ID number", line(max_len=40))
    if not compact:
        form.add("address_line1", "Address", line(max_len=120), span=2)
        form.add("address_line2", "Address line 2", line(max_len=120), span=2)
        form.add("city", "City", line(max_len=80))
        form.add("state", "State / province", line(max_len=60))
        form.add("postal_code", "Postal code", line(max_len=20))
        form.add("country", "Country", line(max_len=60))
        form.add("company", "Company", line(max_len=100))
        form.add("vehicle_plate", "Vehicle plate", line(max_len=20))
        form.add("id_expiry", "ID expiry", OptionalDateEdit())
        form.add("date_of_birth", "Date of birth", OptionalDateEdit())
        form.add("preferences", "Preferences", text_area(placeholder="Room preferences, allergies, special needs…",
                                                          height=60), span=2)
        vip = QCheckBox("VIP guest")
        banned = QCheckBox("Do not rent (blocked from booking)")
        form.add("is_vip", "", vip)
        form.add("is_banned", "", banned)
        form.add("banned_reason", "Reason for do-not-rent", line(max_len=300), span=2)
        form.set_visible("banned_reason", False)
        banned.toggled.connect(lambda on: form.set_visible("banned_reason", on))
    else:
        form.add("vehicle_plate", "Vehicle plate", line(max_len=20))
        form.add("city", "City", line(max_len=80))
    if guest:
        form.set_values({k: getattr(guest, k) for k in form.fields if hasattr(guest, k)})
        if "banned_reason" in form.fields:
            form.set_visible("banned_reason", guest.is_banned)
    return form


class DuplicateDialog(BaseDialog):
    """Warn about likely duplicates before creating a new guest profile."""

    def __init__(self, parent, app, duplicates: list[Guest]):
        super().__init__(parent, "Possible duplicate guest", "A guest with matching details already exists. Use the "
                         "existing profile to keep the guest's history together.", icon_name="users", tone="amber",
                         width=620)
        self.chosen: int | None = None
        table = DataTable([
            Column("name", "Name", stretch=True, bold=True), Column("phone", "Phone", width=140),
            Column("email", "Email", width=180), Column("stays", "Stays", "int", width=60),
        ], app.fmt, row_height=36)
        table.set_rows([{"id": g.id, "name": g.full_name, "phone": g.phone, "email": g.email, "stays": g.stays}
                        for g in duplicates])
        table.setMinimumHeight(150)
        table.view.selectRow(0)
        table.activated.connect(lambda row: self._use(row["id"]))
        self.table = table
        self.body.addWidget(table)
        self.add_footer_button("Cancel", self.reject)
        self.add_footer_button("Create new anyway", lambda: self.done(2))
        self.add_footer_button("Use selected guest", lambda: self._use((table.selected_row() or {}).get("id")),
                               "primary", default=True)

    def _use(self, guest_id) -> None:
        if guest_id:
            self.chosen = guest_id
            self.accept()


class GuestDialog(BaseDialog):
    """New guest (form only) or existing guest profile (header, tabs)."""

    def __init__(self, parent, app, guest_id: int | None = None, *, prefill: dict | None = None):
        self.app = app
        self.ctx = app.ctx
        self.guest_id = guest_id
        guest = self.ctx.guests.get(guest_id) if guest_id else None
        super().__init__(parent, guest.full_name if guest else "New guest",
                         "Guest profile" if guest else "Create a guest profile. Only the name is required.",
                         icon_name="user" if not guest else None, width=760 if guest else 640)
        self.result_value = None
        can_edit = self.ctx.can("guests.edit")
        self.form = self.register_form(guest_form(guest))
        if prefill:
            self.form.set_values(prefill)
        self.form.setEnabled(can_edit)
        if guest:
            self.subtitle_label.hide()
            self.body.addWidget(self._header(guest))
            tabs = QTabWidget()
            profile = QWidget()
            pl = QVBoxLayout(profile)
            pl.setContentsMargins(0, 14, 0, 0)
            pl.addWidget(self.form)
            pl.addStretch(1)
            tabs.addTab(profile, "Profile")
            tabs.addTab(self._history(guest), f"Stays ({len(self.ctx.guests.history(guest.id))})")
            notes = NotesPanel(app, guest_id=guest.id)
            notes.setMinimumHeight(300)
            tabs.addTab(notes, "Notes")
            self.body.addWidget(tabs, 1)
            self.resize(820, 760)
            if self.ctx.can("guests.delete"):
                self.add_footer_button("Delete guest", self._delete, "danger-outline", icon_name="trash", left=True)
            if self.ctx.can("reservations.create") and not guest.is_banned:
                self.add_footer_button("New reservation", self._new_reservation, "soft", icon_name="plus", left=True)
        else:
            self.body.addWidget(self.form)
        self.add_cancel("Close" if guest else "Cancel")
        if can_edit:
            self.add_footer_button("Save changes" if guest else "Create guest", self._save, "primary", default=True)
        self.form.fields["first_name"].setFocus()

    def _header(self, guest: Guest) -> QWidget:
        card = Card(padding=14, spacing=8)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(Avatar(guest.full_name, 52))
        info = QVBoxLayout()
        info.setSpacing(3)
        names = QHBoxLayout()
        names.setSpacing(8)
        names.addWidget(label(guest.full_name, "h2"))
        if guest.in_house:
            names.addWidget(Badge("In house", "blue", small=True))
        if guest.is_vip:
            names.addWidget(Badge("VIP", "amber", small=True))
        if guest.is_banned:
            names.addWidget(Badge("Do not rent", "red", small=True))
        names.addStretch(1)
        info.addLayout(names)
        contact = " · ".join(x for x in (guest.phone, guest.email, guest.city) if x)
        info.addWidget(label(contact or "No contact details on file", "muted"))
        row.addLayout(info, 1)
        fmt = self.app.fmt
        for title, value in (("Stays", str(guest.stays)), ("Nights", str(guest.nights)),
                             ("Total spent", fmt.money(guest.total_spent)),
                             ("Last stay", fmt.date(guest.last_stay) if guest.last_stay else "—")):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(label(title, "overline"))
            box.addWidget(label(value, "kpi_small"))
            row.addSpacing(10)
            row.addLayout(box)
        card.body.addLayout(row)
        if guest.is_banned and guest.banned_reason:
            card.body.addWidget(label(f"Do-not-rent reason: {guest.banned_reason}", "error"))
        return card

    def _history(self, guest: Guest) -> QWidget:
        table = DataTable([
            Column("confirmation_no", "Conf. #", width=90, bold=True),
            Column("check_in_date", "Arrival", "date", width=120),
            Column("check_out_date", "Departure", "date", width=120),
            Column("nights", "Nights", "int", width=60),
            Column("room_number", "Room", width=70),
            Column("status", "Status", "badge", width=110, fmt=lambda r: ReservationStatus.LABELS[r["status"]],
                   tone=lambda r: ReservationStatus.TONES[r["status"]]),
            Column("total", "Total", "money", width=100),
            Column("balance", "Balance", "money", width=100),
        ], self.app.fmt, empty_icon="calendar", empty_title="No stays yet",
            empty_text="Reservations for this guest will appear here.")
        rows = []
        for r in self.ctx.guests.history(guest.id):
            rows.append({"id": r.id, "confirmation_no": r.confirmation_no, "check_in_date": r.check_in_date,
                         "check_out_date": r.check_out_date, "nights": r.nights, "room_number": r.room_number,
                         "status": r.status, "total": self.ctx.billing.estimate(r), "balance": r.balance})
        table.set_rows(rows)
        table.activated.connect(lambda row: self.app.actions.open_reservation(row["id"], parent=self))
        wrapper = QWidget()
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.addWidget(table)
        return wrapper

    def _save(self) -> None:
        values = self.form.values()
        if self.guest_id:
            self.attempt(lambda: (self.ctx.guests.update(self.guest_id, values), self.guest_id)[1])
            return
        duplicates = self.ctx.guests.find_duplicates(values)
        if duplicates:
            dlg = DuplicateDialog(self, self.app, duplicates)
            code = dlg.exec()
            if code == QDialog.DialogCode.Accepted and dlg.chosen:
                self.result_value = dlg.chosen
                self.accept()
                return
            if code != 2:
                return
        self.attempt(lambda: self.ctx.guests.create(values))

    def _delete(self) -> None:
        if confirm(self, "Delete guest", f"Permanently delete {self.title_label.text()}? Guests with stay history "
                   "cannot be deleted.", "Delete guest", danger=True):
            if guarded(self, lambda: self.ctx.guests.delete(self.guest_id)):
                self.app.toast("Guest deleted")
                self.result_value = None
                self.done(QDialog.DialogCode.Accepted)

    def _new_reservation(self) -> None:
        self.accept()
        self.app.actions.new_reservation(guest_id=self.guest_id)


__all__ = ["GuestDialog", "guest_form", "Qt"]
