from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout

from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.common import ChipGroup, SearchField, button, label
from motelmg.ui.widgets.dialogs import confirm, guarded
from motelmg.ui.widgets.table import Column, DataTable


class GuestsPage(Page):
    key = "guests"
    title = "Guests"
    icon = "users"
    permission = "guests.view"
    topics = ("guests", "reservations", "billing")

    def __init__(self, app):
        super().__init__(app)
        L = self.layout_
        top = QHBoxLayout()
        top.setSpacing(10)
        self.chips = ChipGroup([("All guests", "all"), ("In house", "in_house"), ("VIP", "vip"),
                                ("Do not rent", "banned")])
        self.chips.changed.connect(lambda *_: self.mark_stale())
        top.addWidget(self.chips)
        top.addStretch(1)
        self.search = SearchField("Name, phone, email, ID number, plate…")
        self.search.setMinimumWidth(320)
        self.search.search.connect(lambda *_: self.mark_stale())
        top.addWidget(self.search)
        top.addWidget(button("Export", "download", on_click=lambda: self.export_table(self.table, "guests")))
        if self.ctx.can("guests.edit"):
            top.addWidget(button("New guest", "user-plus", "primary", on_click=self._new))
        L.addLayout(top)
        self.table = DataTable([
            Column("name", "Name", width=220, bold=True),
            Column("flags", "", "badge", width=100, fmt=lambda r: r["flag"], tone=lambda r: r["flag_tone"]),
            Column("phone", "Phone", width=140),
            Column("email", "Email", stretch=True),
            Column("city", "City", width=130),
            Column("stays", "Stays", "int", width=60),
            Column("nights", "Nights", "int", width=64),
            Column("total_spent", "Total spent", "money", width=110),
            Column("last_stay", "Last stay", "date", width=120),
        ], self.fmt, empty_icon="users", empty_title="No guests found",
            empty_text="Guest profiles are created when you make a reservation, or add one here.",
            empty_action="New guest" if self.ctx.can("guests.edit") else None)
        self.table.empty.action.connect(self._new)
        self.table.activated.connect(lambda r: self.actions.open_guest(r["id"]))
        self.table.set_menu_builder(self._menu)
        L.addWidget(self.table, 1)
        self.summary = label("", "faint")
        L.addWidget(self.summary)

    def subtitle(self) -> str:
        return "Guest profiles, contact details and stay history"

    def refresh(self) -> None:
        mode = self.chips.current()
        guests = self.ctx.guests.search(self.search.text().strip(), vip_only=mode == "vip",
                                        banned_only=mode == "banned", in_house_only=mode == "in_house")
        rows = []
        for g in guests:
            flag, tone = ("Do not rent", "red") if g.is_banned else ("In house", "blue") if g.in_house else \
                ("VIP", "amber") if g.is_vip else ("", "gray")
            rows.append({"id": g.id, "name": g.display_name, "flag": flag, "flag_tone": tone, "phone": g.phone,
                         "email": g.email, "city": g.city, "stays": g.stays, "nights": g.nights,
                         "total_spent": g.total_spent, "last_stay": g.last_stay})
        self.table.set_rows(rows)
        self.summary.setText(f"{len(rows)} guest(s)" + (" (showing first 1000 — refine your search)"
                                                         if len(rows) >= 1000 else ""))

    def _new(self) -> None:
        guest_id = self.actions.new_guest()
        if guest_id:
            self.mark_stale()
            self.table.select_id(guest_id)

    def _menu(self, row) -> list:
        can = self.ctx.can
        return [("Open profile", lambda: self.actions.open_guest(row["id"])),
                ("New reservation…", lambda: self.actions.new_reservation(guest_id=row["id"]),
                 can("reservations.create") and row["flag"] != "Do not rent"),
                None,
                ("Delete guest…", lambda: self._delete(row), can("guests.delete"))]

    def _delete(self, row) -> None:
        if confirm(self, "Delete guest", f"Permanently delete {row['name']}? Guests with reservations cannot be "
                   "deleted.", "Delete", danger=True):
            guarded(self, lambda: self.ctx.guests.delete(row["id"]), "Guest deleted", self.app.toast)
