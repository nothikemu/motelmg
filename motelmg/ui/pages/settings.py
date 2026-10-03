"""Settings: property, rooms & rates, taxes & fees, payment methods, policies,
receipts, notifications, appearance, backup & restore, about."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from motelmg import APP_DISPLAY_NAME, __version__
from motelmg.core import paths
from motelmg.core.config import DATE_FORMAT_CHOICES, TIME_FORMAT_CHOICES
from motelmg.core.money import COMMON_CURRENCIES, format_percent
from motelmg.ui import theme as theme_mod
from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.common import Banner, Card, button, label
from motelmg.ui.widgets.dialogs import confirm, guarded, inform, show_error
from motelmg.ui.widgets.forms import FormGrid, MoneyEdit, combo, line, spin, text_area
from motelmg.ui.widgets.table import Column, DataTable

SECTIONS = [
    ("property", "Property", "building", "settings.manage"),
    ("rooms", "Rooms & rates", "bed", "rooms.manage"),
    ("billing", "Taxes, fees & discounts", "percent", "settings.manage"),
    ("payments", "Payment methods", "card", "settings.manage"),
    ("policies", "Front desk policies", "clock", "settings.manage"),
    ("receipts", "Invoices & receipts", "receipt", "settings.manage"),
    ("notifications", "Notifications", "bell", "settings.manage"),
    ("appearance", "Regional & appearance", "sun", "settings.manage"),
    ("backup", "Backup & restore", "database", "backup.manage"),
    ("about", "About", "info", ""),
]


def open_folder(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class SettingsPanel(QWidget):
    """A section: settings-bound form with a Save button, plus free content."""

    def __init__(self, page: "SettingsPage", title: str, subtitle: str = ""):
        super().__init__()
        self.setObjectName("Transparent")
        self.page = page
        self.ctx = page.ctx
        self.bindings: dict[str, tuple[QWidget, str]] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        host.setObjectName("PageBody")
        self.body = QVBoxLayout(host)
        self.body.setContentsMargins(0, 0, 8, 0)
        self.body.setSpacing(14)
        scroll.setWidget(host)
        outer.addWidget(scroll)
        self.body.addWidget(label(title, "h2"))
        if subtitle:
            self.body.addWidget(label(subtitle, "muted", wrap=True))
        self.banner = Banner("", "error", closable=True)
        self.body.addWidget(self.banner)
        self.form: FormGrid | None = None

    def bind(self, form: FormGrid, key: str, setting: str, widget: QWidget, title: str, kind: str = "text",
             **kwargs) -> QWidget:
        form.add(setting, title, widget, **kwargs)
        self.bindings[setting] = (widget, kind)
        return widget

    def load(self) -> None:
        s = self.ctx.settings
        for setting, (widget, kind) in self.bindings.items():
            value = s.get(setting)
            if kind == "money":
                widget.set_cents(int(value or 0))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif kind == "int":
                widget.setValue(int(value or 0))
            elif hasattr(widget, "setCurrentIndex"):
                idx = widget.findData(value)
                widget.setCurrentIndex(max(idx, 0))
            elif hasattr(widget, "setPlainText"):
                widget.setPlainText(str(value or ""))
            elif hasattr(widget, "set_value"):
                widget.set_value(value)
            else:
                widget.setText(str(value or ""))

    def values(self) -> dict:
        out = {}
        for setting, (widget, kind) in self.bindings.items():
            if kind == "money":
                out[setting] = widget.cents()
            elif isinstance(widget, QCheckBox):
                out[setting] = widget.isChecked()
            elif kind == "int":
                out[setting] = widget.value()
            elif hasattr(widget, "currentData"):
                out[setting] = widget.currentData()
            elif hasattr(widget, "toPlainText"):
                out[setting] = widget.toPlainText().strip()
            elif hasattr(widget, "value") and callable(widget.value) and not hasattr(widget, "text"):
                out[setting] = widget.value()
            else:
                out[setting] = widget.text().strip()
        return out

    def save_button(self, extra=None) -> None:
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Revert", "undo", "ghost", on_click=self.load))
        row.addWidget(button("Save changes", "check", "primary", on_click=lambda: self.save(extra)))
        self.body.addLayout(row)

    def save(self, extra=None) -> None:
        self.banner.hide()
        if self.form:
            self.form.clear_errors()
        values = self.values()
        try:
            self.ctx.settings.update(values)
            if extra:
                extra(values)
        except Exception as exc:  # noqa: BLE001
            from motelmg.core.errors import ValidationError
            if isinstance(exc, ValidationError) and self.form and self.form.set_errors(exc.field_errors):
                self.banner.set("Please correct the highlighted fields.", "error")
            elif hasattr(exc, "message"):
                self.banner.set(exc.message, "error")
            else:
                show_error(self, exc)
            return
        self.page.app.toast("Settings saved")


class SettingsPage(Page):
    key = "settings"
    title = "Settings"
    icon = "settings"
    permission = ""
    topics = ("settings", "rooms", "catalog", "backups")

    @classmethod
    def allowed(cls, ctx) -> bool:
        return any(ctx.can(p) for p in ("settings.manage", "rooms.manage", "backup.manage"))

    def __init__(self, app):
        super().__init__(app)
        body = QHBoxLayout()
        body.setSpacing(18)
        nav = Card(padding=10, spacing=4)
        nav.setFixedWidth(240)
        self.nav = QListWidget()
        self.nav.setStyleSheet("QListWidget { border: none; background: transparent; }")
        nav.body.addWidget(self.nav)
        body.addWidget(nav)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.layout_.addLayout(body, 1)
        self.panels: dict[str, SettingsPanel] = {}
        builders = {"property": self._property, "rooms": self._rooms, "billing": self._billing,
                    "payments": self._payments, "policies": self._policies, "receipts": self._receipts,
                    "notifications": self._notifications, "appearance": self._appearance, "backup": self._backup,
                    "about": self._about}
        from motelmg.ui.icons import icon
        for key, title, icon_name, perm in SECTIONS:
            if perm and not self.ctx.can(perm):
                continue
            panel = builders[key]()
            self.panels[key] = panel
            self.stack.addWidget(panel)
            item = QListWidgetItem(f"  {title}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setIcon(icon(icon_name, theme_mod.theme().c["text_muted"], 16))
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._switch)
        self.nav.setCurrentRow(0)

    def subtitle(self) -> str:
        return "Configure the property, rates, policies and the application"

    def on_show(self, **kwargs) -> None:
        section = kwargs.get("section")
        if section:
            for i in range(self.nav.count()):
                if self.nav.item(i).data(Qt.ItemDataRole.UserRole) == section:
                    self.nav.setCurrentRow(i)
        super().on_show(**kwargs)

    def _switch(self, row: int) -> None:
        item = self.nav.item(row)
        if not item:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        panel = self.panels[key]
        self.stack.setCurrentWidget(panel)
        if hasattr(panel, "reload"):
            panel.reload()

    def refresh(self) -> None:
        for panel in self.panels.values():
            if hasattr(panel, "reload"):
                panel.reload()
            elif panel.bindings:
                panel.load()

    # -- sections ---------------------------------------------------------------------------------------------
    def _simple(self, title: str, subtitle: str, fields: list[tuple], columns: int = 2, extra=None) -> SettingsPanel:
        panel = SettingsPanel(self, title, subtitle)
        card = Card(padding=18)
        form = FormGrid(columns)
        panel.form = form
        for f in fields:
            setting, label_text, widget, kind, kwargs = (f + ("text", {}))[:5] if len(f) == 3 else \
                (f + ({},))[:5] if len(f) == 4 else f
            panel.bind(form, setting, setting, widget, label_text, kind, **kwargs)
        card.body.addWidget(form)
        panel.body.addWidget(card)
        panel.save_button(extra)
        panel.body.addStretch(1)
        panel.load()
        return panel

    def _property(self) -> SettingsPanel:
        return self._simple("Property", "Shown on invoices, receipts and registration cards.", [
            ("property.name", "Motel name", line(max_len=100), "text", {"required": True, "span": 2}),
            ("property.address1", "Address", line(max_len=120), "text", {"span": 2}),
            ("property.address2", "Address line 2", line(max_len=120), "text", {"span": 2}),
            ("property.city", "City", line(max_len=80)),
            ("property.state", "State / province", line(max_len=60)),
            ("property.postal_code", "Postal code", line(max_len=20)),
            ("property.country", "Country", line(max_len=60)),
            ("property.phone", "Phone", line(max_len=30)),
            ("property.email", "Email", line(max_len=120)),
            ("property.website", "Website", line(max_len=120)),
            ("property.tax_id", "Tax / business ID", line(max_len=60)),
        ])

    def _policies(self) -> SettingsPanel:
        return self._simple("Front desk policies", "Times and rules used for check-in, check-out and bookings. Early "
                            "check-in and late check-out fee amounts are set under Taxes, fees & discounts.", [
                                ("policy.check_in_time", "Check-in time", line(max_len=8), "text",
                                 {"hint": "24h format, e.g. 15:00"}),
                                ("policy.check_out_time", "Check-out time", line(max_len=8), "text",
                                 {"hint": "e.g. 11:00"}),
                                ("policy.early_checkin_grace_minutes", "Early check-in grace", spin(0, 0, 600, " min"),
                                 "int", {"hint": "Arrivals within this window are not 'early'"}),
                                ("policy.late_checkout_grace_minutes", "Late check-out grace", spin(0, 0, 600, " min"),
                                 "int", {"hint": "Guests are overdue after check-out time + grace"}),
                                ("policy.max_nights", "Maximum stay", spin(1, 1, 365, " nights"), "int"),
                                ("policy.booking_horizon_days", "Book up to", spin(30, 30, 1825, " days ahead"), "int"),
                                ("policy.deposit_percent", "Suggested deposit", spin(0, 0, 100, " %"), "int",
                                 {"hint": "Of the stay total, 0 = first night"}),
                                ("policy.require_guest_id", "", QCheckBox("Require an ID document at check-in"),
                                 "bool", {"span": 2}),
                                ("policy.require_inspection", "", QCheckBox(
                                    "Rooms must be inspected (not just cleaned) before they are ready to sell"),
                                 "bool", {"span": 2}),
                            ])

    def _receipts(self) -> SettingsPanel:
        return self._simple("Invoices & receipts", "Numbering and wording of printed documents.", [
            ("numbering.reservation_prefix", "Reservation prefix", line(max_len=8)),
            ("numbering.invoice_prefix", "Invoice prefix", line(max_len=8)),
            ("numbering.receipt_prefix", "Receipt prefix", line(max_len=8)),
            ("invoice.paper_size", "Paper size", combo([("Letter", "Letter"), ("A4", "A4")])),
            ("invoice.header_text", "Header note", line(max_len=200), "text", {"span": 2}),
            ("invoice.footer_text", "Footer message", text_area("", "", 60), "text", {"span": 2}),
            ("invoice.show_tax_breakdown", "", QCheckBox("Show each tax separately in totals"), "bool", {"span": 2}),
            ("invoice.show_tax_lines", "", QCheckBox("List individual tax lines on invoices"), "bool", {"span": 2}),
            ("invoice.print_registration_card", "", QCheckBox("Offer to print a registration card at every check-in"),
             "bool", {"span": 2}),
        ])

    def _notifications(self) -> SettingsPanel:
        boxes = [
            ("notify.overdue", "Overdue check-outs"), ("notify.conflicts", "Booking conflicts"),
            ("notify.arrivals", "Upcoming and late arrivals"), ("notify.departures", "Departures due today"),
            ("notify.no_shows", "Possible no-shows"), ("notify.balances", "Unpaid balances and refunds due"),
            ("notify.housekeeping", "Rooms needing cleaning"), ("notify.maintenance", "Maintenance and room blocks"),
            ("notify.system", "System events (backups, restores)"),
            ("notify.toasts", "Pop-up toast when a new critical alert appears"),
        ]
        fields = [(key, "", QCheckBox(text), "bool", {}) for key, text in boxes]
        fields += [("notify.arrival_window_hours", "Arriving-soon window", spin(0, 0, 24, " hours"), "int", {}),
                   ("notify.balance_threshold", "Ignore balances below", spin(0, 0, 10000, ""), "int",
                    {"hint": "Whole currency units"})]
        return self._simple("Notifications", "Choose which alerts appear in the bell menu and on the dashboard.",
                            fields, extra=lambda v: setattr(self.app.toasts, "enabled", v["notify.toasts"]))

    def _appearance(self) -> SettingsPanel:
        currencies = [(f"{code} — {name} ({sym.strip()})", code) for code, name, sym, _ in COMMON_CURRENCIES]
        self._currency = combo(currencies)
        panel = self._simple("Regional & appearance", "Currency, date formats, theme and security.", [
            ("currency.code", "Currency", self._currency, "text", {"span": 2}),
            ("currency.symbol", "Currency symbol", line(max_len=5)),
            ("currency.decimals", "Decimals", spin(2, 0, 2), "int"),
            ("currency.symbol_after", "", QCheckBox("Symbol after the amount (e.g. 10,00 €)"), "bool"),
            ("currency.thousands_sep", "Thousands separator", combo([(", (comma)", ","), (". (period)", "."),
                                                                     ("space", " "), ("none", "")])),
            ("currency.decimal_sep", "Decimal separator", combo([(". (period)", "."), (", (comma)", ",")])),
            ("app.date_format", "Date format", combo([(f"{example}  ({fmt})", fmt)
                                                     for fmt, example in DATE_FORMAT_CHOICES])),
            ("app.time_format", "Time format", combo([(example, fmt) for fmt, example in TIME_FORMAT_CHOICES])),
            ("app.theme", "Theme", combo([("Light", "light"), ("Dark", "dark"), ("Match system", "system")])),
            ("app.auto_lock_minutes", "Auto-lock after", spin(0, 0, 240, " min idle"), "int",
             {"hint": "0 = never lock automatically"}),
        ], extra=lambda v: (theme_mod.theme_manager.apply(v["app.theme"]), self.app.refresh_soon()))

        def currency_changed() -> None:
            code = self._currency.currentData()
            for c, _, sym, dec in COMMON_CURRENCIES:
                if c == code:
                    panel.bindings["currency.symbol"][0].setText(sym)
                    panel.bindings["currency.decimals"][0].setValue(dec)
        self._currency.activated.connect(lambda *_: currency_changed())
        return panel

    def _about(self) -> SettingsPanel:
        panel = SettingsPanel(self, "About", f"{APP_DISPLAY_NAME} {__version__} — motel management system")
        card = Card(padding=18)
        info = [("Version", __version__), ("Data folder", str(paths.data_dir())),
                ("Database", str(self.ctx.db.path)), ("Logs", str(paths.logs_dir())),
                ("Python", sys.version.split()[0])]
        from motelmg.ui.widgets.common import KeyValueGrid
        grid = KeyValueGrid()
        for k, v in info:
            grid.add(k, k, v)
        card.body.addWidget(grid)
        row = QHBoxLayout()
        row.addWidget(button("Open data folder", "folder", on_click=lambda: open_folder(paths.data_dir())))
        row.addWidget(button("Open logs", "file", on_click=lambda: open_folder(paths.logs_dir())))
        row.addWidget(button("Check database integrity", "shield", on_click=self._integrity))
        row.addStretch(1)
        card.body.addLayout(row)
        panel.body.addWidget(card)
        panel.body.addWidget(label("All data is stored locally in a single SQLite database file. Back it up from "
                                   "Backup & restore, or copy the data folder while the application is closed.",
                                   "faint", wrap=True))
        panel.body.addStretch(1)
        return panel

    def _integrity(self) -> None:
        result = guarded(self, self.ctx.db.integrity_check)
        if result == "ok":
            inform(self, "Database check", "The database passed the integrity check. No problems were found.",
                   icon_name="check-circle", tone="green")
        elif result:
            inform(self, "Database check", f"Problems were found: {result}. Restore the most recent backup.",
                   icon_name="alert", tone="red")

    # -- rooms & rates -----------------------------------------------------------------------------------------
    def _rooms(self) -> SettingsPanel:
        panel = SettingsPanel(self, "Rooms & rates", "Room types set the standard nightly rate. Individual rooms "
                              "can override it.")
        fmt = self.fmt
        types_card = Card("Room types", padding=16)
        types_card.add_action(button("Add room type", "plus", "soft", small=True, on_click=lambda: self._edit_type()))
        types = DataTable([
            Column("code", "Code", width=70, bold=True), Column("name", "Name", stretch=True),
            Column("beds", "Beds", width=140), Column("max_occupancy", "Sleeps", "int", width=70),
            Column("base_rate", "Rate", "money", width=100), Column("room_count", "Rooms", "int", width=70),
            Column("active", "", "badge", width=90, fmt=lambda r: "" if r["is_active"] else "Inactive",
                   tone=lambda r: "gray"),
        ], fmt, empty_icon="layers", empty_title="No room types", row_height=34)
        types.setMinimumHeight(200)
        types.activated.connect(lambda r: self._edit_type(r["id"]))
        types.set_menu_builder(lambda r: [("Edit…", lambda: self._edit_type(r["id"])),
                                          ("Delete…", lambda: self._delete_type(r))])
        types_card.body.addWidget(types)
        panel.body.addWidget(types_card)
        rooms_card = Card("Rooms", padding=16)
        rooms_card.add_action(button("Add several", "grid", small=True, on_click=self._bulk_rooms))
        rooms_card.add_action(button("Add room", "plus", "soft", small=True, on_click=lambda: self._edit_room()))
        rooms = DataTable([
            Column("number", "Room", width=70, bold=True), Column("type_name", "Type", stretch=True),
            Column("floor", "Floor", width=70), Column("beds", "Beds", width=140),
            Column("capacity", "Sleeps", "int", width=70), Column("rate", "Rate", "money", width=100),
            Column("status", "", "badge", width=110, fmt=lambda r: r["status_label"], tone=lambda r: r["tone"]),
        ], fmt, empty_icon="bed", empty_title="No rooms yet", empty_text="Add rooms so you can start taking "
                                                                          "reservations.", row_height=34)
        rooms.setMinimumHeight(320)
        rooms.activated.connect(lambda r: self._edit_room(r["id"]))
        rooms.set_menu_builder(lambda r: [("Edit…", lambda: self._edit_room(r["id"])),
                                          ("Delete / archive…", lambda: self._delete_room(r))])
        rooms_card.body.addWidget(rooms)
        panel.body.addWidget(rooms_card)
        show_archived = QCheckBox("Show archived rooms")
        panel.body.addWidget(show_archived)

        def reload():
            types.set_rows([{"id": t.id, "code": t.code, "name": t.name, "beds": t.beds,
                             "max_occupancy": t.max_occupancy, "base_rate": t.base_rate, "room_count": t.room_count,
                             "is_active": t.is_active} for t in self.ctx.rooms.list_types(include_inactive=True)])
            rows = []
            for r in self.ctx.rooms.list_rooms(include_inactive=show_archived.isChecked()):
                label_, tone = ("Archived", "gray") if not r.is_active else (
                    ("Out of order", "orange") if r.service_status != "in_service" else ("", "gray"))
                rows.append({"id": r.id, "number": r.number, "type_name": r.type_name, "floor": r.floor,
                             "beds": r.effective_beds, "capacity": r.capacity, "rate": r.effective_rate,
                             "status_label": label_, "tone": tone})
            rooms.set_rows(rows)
        show_archived.toggled.connect(lambda *_: reload())
        panel.reload = reload  # type: ignore[attr-defined]
        reload()
        return panel

    def _edit_type(self, type_id=None) -> None:
        from motelmg.ui.dialogs.property import RoomTypeDialog
        RoomTypeDialog(self, self.app, type_id).exec()

    def _delete_type(self, row) -> None:
        if confirm(self, "Delete room type", f"Delete '{row['name']}'? Types that are in use can only be "
                   "deactivated.", "Delete", danger=True):
            guarded(self, lambda: self.ctx.rooms.delete_type(row["id"]), "Room type deleted", self.app.toast)

    def _edit_room(self, room_id=None) -> None:
        from motelmg.ui.dialogs.property import RoomDialog
        RoomDialog(self, self.app, room_id).exec()

    def _bulk_rooms(self) -> None:
        from motelmg.ui.dialogs.property import BulkRoomsDialog
        BulkRoomsDialog(self, self.app).exec()

    def _delete_room(self, row) -> None:
        if confirm(self, "Remove room", f"Remove room {row['number']}? Rooms with past stays are archived instead "
                   "so their history is kept.", "Remove", danger=True):
            result = guarded(self, lambda: self.ctx.rooms.delete_room(row["id"]))
            if result:
                self.app.toast(f"Room {row['number']} {result}")

    # -- billing catalog ---------------------------------------------------------------------------------------
    def _billing(self) -> SettingsPanel:
        panel = SettingsPanel(self, "Taxes, fees & discounts", "Taxes are calculated on each charge when it is "
                              "posted. Fees marked 'automatic' are added at check-in.")
        fmt = self.fmt
        taxes_card = Card("Taxes", padding=16)
        taxes_card.add_action(button("Add tax", "plus", "soft", small=True, on_click=lambda: self._edit_tax()))
        taxes = DataTable([
            Column("name", "Name", stretch=True, bold=True), Column("rate", "Rate", width=130),
            Column("applies", "Applies to", width=150), Column("active", "", "badge", width=90,
                                                               fmt=lambda r: "" if r["is_active"] else "Inactive",
                                                               tone=lambda r: "gray"),
        ], fmt, empty_icon="percent", empty_title="No taxes configured",
            empty_text="Add the sales / occupancy taxes your property must charge.", row_height=34)
        taxes.setMinimumHeight(150)
        taxes.activated.connect(lambda r: self._edit_tax(r["tax"]))
        taxes.set_menu_builder(lambda r: [("Edit…", lambda: self._edit_tax(r["tax"])),
                                          ("Delete…", lambda: self._delete_catalog("taxes", r))])
        taxes_card.body.addWidget(taxes)
        panel.body.addWidget(taxes_card)
        items_card = Card("Fees & extra charges", padding=16)
        items_card.add_action(button("Add charge item", "plus", "soft", small=True, on_click=lambda: self._edit_item()))
        items = DataTable([
            Column("name", "Name", stretch=True, bold=True), Column("category", "Type", width=80),
            Column("amount", "Default", "money", width=100), Column("taxable", "Taxable", width=80),
            Column("auto", "Automatic", width=120), Column("system", "", "badge", width=90,
                                                         fmt=lambda r: "Built-in" if r["system"] else
                                                         ("Inactive" if not r["is_active"] else ""),
                                                         tone=lambda r: "indigo" if r["system"] else "gray"),
        ], fmt, empty_icon="tag", empty_title="No charge items", row_height=34)
        items.setMinimumHeight(260)
        items.activated.connect(lambda r: self._edit_item(r["item"]))
        items.set_menu_builder(lambda r: [("Edit…", lambda: self._edit_item(r["item"])),
                                          ("Delete…", lambda: self._delete_catalog("charge_items", r),
                                           not r["system"])])
        items_card.body.addWidget(items)
        panel.body.addWidget(items_card)
        disc_card = Card("Discounts", padding=16)
        disc_card.add_action(button("Add discount", "plus", "soft", small=True, on_click=lambda: self._edit_discount()))
        discounts = DataTable([
            Column("name", "Name", stretch=True, bold=True), Column("percent", "Discount", width=100),
            Column("active", "", "badge", width=90, fmt=lambda r: "" if r["is_active"] else "Inactive",
                   tone=lambda r: "gray"),
        ], fmt, empty_icon="percent", empty_title="No discounts", row_height=34)
        discounts.setMinimumHeight(170)
        discounts.activated.connect(lambda r: self._edit_discount(r["discount"]))
        discounts.set_menu_builder(lambda r: [("Edit…", lambda: self._edit_discount(r["discount"])),
                                              ("Delete…", lambda: self._delete_catalog("discount_types", r))])
        disc_card.body.addWidget(discounts)
        panel.body.addWidget(disc_card)

        def reload():
            taxes.set_rows([{"id": t.id, "name": t.name, "tax": t, "is_active": t.is_active,
                             "rate": format_percent(t.value) if t.kind == "percent" else f"{fmt.money(t.value)} / night",
                             "applies": {"all": "All charges", "room": "Room charges", "extras": "Extras only"}[
                                 t.applies_to]} for t in self.ctx.catalog.taxes(include_inactive=True)])
            items.set_rows([{"id": i.id, "name": i.name, "item": i, "category": i.category.title(),
                             "amount": i.default_amount, "taxable": "Yes" if i.taxable else "No",
                             "auto": {"none": "—", "per_night": "Every night", "per_stay": "Once per stay"}[
                                 i.auto_apply], "system": bool(i.system_code), "is_active": i.is_active}
                            for i in self.ctx.catalog.charge_items(include_inactive=True)])
            discounts.set_rows([{"id": d.id, "name": d.name, "discount": d, "percent": format_percent(d.percent_bp),
                                 "is_active": d.is_active} for d in self.ctx.catalog.discount_types(True)])
        panel.reload = reload  # type: ignore[attr-defined]
        reload()
        return panel

    def _edit_tax(self, tax=None) -> None:
        from motelmg.ui.dialogs.misc import RecordDialog
        kind = combo([("Percentage", "percent"), ("Fixed amount per night", "fixed_per_night")],
                     tax.kind if tax else "percent")
        applies = combo([("All charges", "all"), ("Room charges only", "room"), ("Extras only", "extras")],
                        tax.applies_to if tax else "all")
        value = line((format_percent(tax.value).rstrip("%") if tax.kind == "percent" else f"{tax.value / 100:.2f}")
                     if tax else "", "e.g. 8.25 (%) or 2.00 (per night)", 12)
        active = QCheckBox("Active")
        active.setChecked(tax.is_active if tax else True)
        RecordDialog(self, "Edit tax" if tax else "New tax", [
            ("name", "Name", line(tax.name if tax else "", "e.g. State sales tax", 60), True),
            ("kind", "Type", kind, False), ("value", "Rate / amount", value, False),
            ("applies_to", "Applies to", applies, False), ("is_active", "", active, False),
        ], lambda v: self.ctx.catalog.save_tax(tax.id if tax else None, v),
            subtitle="New rates apply to charges posted from now on.", icon_name="percent").exec()

    def _edit_item(self, item=None) -> None:
        from motelmg.ui.dialogs.misc import RecordDialog
        system = bool(item and item.system_code)
        taxable = QCheckBox("Taxable")
        taxable.setChecked(item.taxable if item else True)
        active = QCheckBox("Active")
        active.setChecked(item.is_active if item else True)
        auto = combo([("No — added manually", "none"), ("Every night of the stay", "per_night"),
                      ("Once per stay", "per_stay")], item.auto_apply if item else "none")
        auto.setEnabled(not system)
        name = line(item.name if item else "", "e.g. Pet fee", 60)
        RecordDialog(self, "Edit charge item" if item else "New charge item", [
            ("name", "Name", name, True),
            ("category", "Type", combo([("Fee", "fee"), ("Extra", "extra")], item.category if item else "extra"), False),
            ("default_amount", "Default amount", MoneyEdit(item.default_amount if item else None), False),
            ("auto_apply", "Add automatically", auto, False),
            ("taxable", "", taxable, False), ("is_active", "", active, False),
        ], lambda v: self.ctx.catalog.save_charge_item(item.id if item else None, v),
            subtitle="Built-in fees (early check-in, late check-out, cancellation, no-show) are used by the front desk "
                     "workflows." if system else "", icon_name="tag").exec()

    def _edit_discount(self, discount=None) -> None:
        from motelmg.ui.dialogs.misc import RecordDialog
        active = QCheckBox("Active")
        active.setChecked(discount.is_active if discount else True)
        RecordDialog(self, "Edit discount" if discount else "New discount", [
            ("name", "Name", line(discount.name if discount else "", "e.g. AAA", 60), True),
            ("percent", "Percent off", line(format_percent(discount.percent_bp).rstrip("%") if discount else "",
                                            "e.g. 10", 6), False),
            ("is_active", "", active, False),
        ], lambda v: self.ctx.catalog.save_discount(discount.id if discount else None, v), icon_name="percent").exec()

    def _delete_catalog(self, table: str, row) -> None:
        if confirm(self, "Delete", f"Delete '{row['name']}'? Items already used on folios can only be deactivated.",
                   "Delete", danger=True):
            guarded(self, lambda: self.ctx.catalog.delete(table, row["id"]), "Deleted", self.app.toast)

    # -- payment methods -----------------------------------------------------------------------------------------
    def _payments(self) -> SettingsPanel:
        panel = SettingsPanel(self, "Payment methods", "Methods offered when taking payments, deposits and refunds.")
        card = Card(padding=16)
        card.add_action(button("Add method", "plus", "soft", small=True, on_click=lambda: self._edit_method()))
        table = DataTable([
            Column("name", "Method", stretch=True, bold=True), Column("ref", "Reference required", width=150),
            Column("cash", "Cash", width=80), Column("active", "", "badge", width=90,
                                                     fmt=lambda r: "" if r["is_active"] else "Inactive",
                                                     tone=lambda r: "gray"),
        ], self.fmt, empty_icon="card", empty_title="No payment methods", row_height=34)
        table.setMinimumHeight(280)
        table.activated.connect(lambda r: self._edit_method(r["method"]))
        table.set_menu_builder(lambda r: [("Edit…", lambda: self._edit_method(r["method"])),
                                          ("Delete…", lambda: self._delete_catalog("payment_methods", r))])
        card.body.addWidget(table)
        panel.body.addWidget(card)
        panel.body.addStretch(1)

        def reload():
            table.set_rows([{"id": m.id, "name": m.name, "method": m, "ref": "Yes" if m.requires_reference else "",
                             "cash": "Yes" if m.is_cash else "", "is_active": m.is_active}
                            for m in self.ctx.catalog.payment_methods(include_inactive=True)])
        panel.reload = reload  # type: ignore[attr-defined]
        reload()
        return panel

    def _edit_method(self, method=None) -> None:
        from motelmg.ui.dialogs.misc import RecordDialog
        ref = QCheckBox("Require a reference (card last 4, check no.)")
        ref.setChecked(method.requires_reference if method else False)
        cash = QCheckBox("Cash (offer change calculation)")
        cash.setChecked(method.is_cash if method else False)
        active = QCheckBox("Active")
        active.setChecked(method.is_active if method else True)
        RecordDialog(self, "Edit payment method" if method else "New payment method", [
            ("name", "Name", line(method.name if method else "", "e.g. Mobile payment", 40), True),
            ("requires_reference", "", ref, True), ("is_cash", "", cash, True), ("is_active", "", active, True),
        ], lambda v: self.ctx.catalog.save_payment_method(method.id if method else None, v), icon_name="card").exec()

    # -- backup & restore ---------------------------------------------------------------------------------------
    def _backup(self) -> SettingsPanel:
        panel = self._simple("Backup & restore", "Backups are complete copies of the database. Keep copies on "
                             "another drive or cloud folder for safety.", [
                                 ("backup.auto_enabled", "", QCheckBox("Back up automatically"), "bool", {"span": 2}),
                                 ("backup.frequency", "How often", combo([("Every day", "daily"),
                                                                          ("Every week", "weekly"),
                                                                          ("When the application closes", "on_exit")])),
                                 ("backup.keep", "Keep the newest", spin(14, 1, 365, " automatic backups"), "int"),
                                 ("backup.directory", "Backup folder", line(max_len=500), "text",
                                  {"span": 2, "hint": "Leave empty for the default folder in the data directory"}),
                             ])
        choose = button("Choose folder…", "folder", small=True, on_click=lambda: self._choose_backup_dir(panel))
        panel.body.insertWidget(panel.body.count() - 2, choose, 0, Qt.AlignmentFlag.AlignLeft)
        card = Card("Backups", padding=16)
        actions = QHBoxLayout()
        actions.addWidget(button("Back up now", "download", "primary", on_click=self._backup_now))
        actions.addWidget(button("Restore selected…", "upload", on_click=lambda: self._restore(table)))
        actions.addWidget(button("Restore from file…", "folder", on_click=lambda: self._restore(None)))
        actions.addStretch(1)
        actions.addWidget(button("Open backup folder", "folder", "ghost",
                                 on_click=lambda: open_folder(self.ctx.backups.directory())))
        card.body.addLayout(actions)
        table = DataTable([
            Column("created", "Created", "datetime", width=180), Column("label", "Type", width=140),
            Column("name", "File", stretch=True), Column("size", "Size", width=90),
        ], self.fmt, empty_icon="database", empty_title="No backups yet",
            empty_text="Click 'Back up now' to create your first backup.", row_height=34)
        table.setMinimumHeight(260)
        card.body.addWidget(table)
        panel.body.insertWidget(panel.body.count() - 1, card)
        panel.body.insertWidget(panel.body.count() - 1, Banner(
            "Restoring replaces ALL current data with the backup. A safety copy of the current data is made first, "
            "and everyone is signed out.", "warning"))

        def reload():
            panel.load()
            rows = []
            for i, b in enumerate(self.ctx.backups.list()):
                rows.append({"id": i, "created": b.created, "label": (b.label or "manual").capitalize(),
                             "name": b.path.name, "size": f"{b.size / 1024 / 1024:.1f} MB" if b.size > 1024 * 1024
                             else f"{b.size / 1024:.0f} KB", "path": b.path})
            table.set_rows(rows)
        panel.reload = reload  # type: ignore[attr-defined]
        reload()
        return panel

    def _choose_backup_dir(self, panel) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Backup folder", str(self.ctx.backups.directory()))
        if folder:
            panel.bindings["backup.directory"][0].setText(folder)

    def _backup_now(self) -> None:
        path = guarded(self, lambda: self.ctx.backups.backup_now("manual"))
        if path:
            self.app.toast(f"Backup saved: {Path(path).name}")
            self.panels["backup"].reload()

    def _restore(self, table) -> None:
        if table is not None:
            row = table.selected_row()
            if not row:
                self.app.toast("Select a backup in the list first", "info")
                return
            path = row["path"]
        else:
            file, _ = QFileDialog.getOpenFileName(self, "Choose a backup", str(self.ctx.backups.directory()),
                                                  "MotelMG database (*.db);;All files (*)")
            if not file:
                return
            path = Path(file)
        details = guarded(self, lambda: self.ctx.backups.inspect(path))
        if not details:
            return
        if not confirm(self, "Restore backup", f"Restore <b>{path.name}</b>?<br><br>It contains "
                       f"{details.rooms} rooms, {details.guests} guests and {details.reservations} reservations "
                       f"for '{details.property_name}'.<br><br>All current data will be replaced and you will be "
                       "signed out. A safety copy of the current data is kept.", "Restore and sign out", danger=True):
            return
        safety = guarded(self, lambda: self.ctx.backups.restore(path))
        if safety:
            inform(self, "Restore complete", f"The database was restored. The previous data was saved as "
                   f"{Path(safety).name}. Please sign in again.", icon_name="check-circle", tone="green")
            self.app.restored.emit()


__all__ = ["SettingsPage"]
