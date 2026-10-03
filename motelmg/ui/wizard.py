"""First-launch setup wizard: property, administrator, rates, room types, rooms."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from motelmg import APP_DISPLAY_NAME
from motelmg.core import paths
from motelmg.core.errors import MotelError, ValidationError
from motelmg.core.money import COMMON_CURRENCIES, parse_amount
from motelmg.services.setup import DEFAULT_ROOM_TYPES, DEFAULT_ROOMS, SetupService
from motelmg.ui.icons import app_icon
from motelmg.ui.widgets.common import Banner, Card, LoadingOverlay, button, label, set_icon, toolbar
from motelmg.ui.widgets.forms import FormGrid, combo, line, spin
from motelmg.ui.dialogs.staff import password_field

STEPS = ["Welcome", "Your property", "Administrator", "Rates & policies", "Room types", "Rooms", "Finish"]


class SetupWizard(QDialog):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.service = SetupService(ctx)
        self.setWindowTitle(f"Set up {APP_DISPLAY_NAME}")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(860, 540)
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        # Leave room for the title bar on small (e.g. 1280x720) screens.
        self.resize(min(1000, avail.width() - 24) if avail else 1000, min(680, avail.height() - 48) if avail else 680)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        side = QFrame()
        side.setObjectName("StepList")
        side.setFixedWidth(240)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(24, 28, 20, 24)
        sl.setSpacing(14)
        logo = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(app_icon().pixmap(36, 36))
        logo.addWidget(ic)
        logo.addWidget(label(APP_DISPLAY_NAME, "h2"))
        logo.addStretch(1)
        sl.addLayout(logo)
        sl.addSpacing(16)
        self.step_labels: list[QLabel] = []
        for i, name in enumerate(STEPS):
            lbl = QLabel(f"{i + 1}.  {name}")
            self.step_labels.append(lbl)
            sl.addWidget(lbl)
        sl.addStretch(1)
        sl.addWidget(label("You can change everything later in Settings.", "faint", wrap=True))
        root.addWidget(side)
        right = QVBoxLayout()
        right.setContentsMargins(36, 28, 36, 20)
        right.setSpacing(14)
        self.banner = Banner("", "error", closable=True)
        right.addWidget(self.banner)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.back_btn = button("Back", "chevron-left", on_click=self._back)
        self.next_btn = button("Continue", None, "primary", on_click=self._next)
        self.next_btn.setMinimumWidth(140)
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        nav.addWidget(self.next_btn)
        right.addLayout(nav)
        host = QWidget()
        host.setObjectName("Page")
        host.setLayout(right)
        root.addWidget(host, 1)
        self.overlay = LoadingOverlay(host)
        for builder in (self._welcome, self._property, self._admin, self._rates, self._types, self._rooms,
                        self._finish):
            self.stack.addWidget(builder())
        self._go(0)

    # -- pages -----------------------------------------------------------------------------------------------
    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("Transparent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(label(title, "h1"))
        layout.addWidget(label(subtitle, "muted", wrap=True))
        return page, layout

    def _welcome(self) -> QWidget:
        page, layout = self._page(f"Welcome to {APP_DISPLAY_NAME}",
                                  "Let's get your motel ready in a few minutes. This wizard will set up your property "
                                  "details, your administrator login, rates and taxes, and your rooms.")
        card = Card(padding=20, spacing=12)
        for icon_name, title, text in (
                ("building", "Your property", "Name, address and contact details for invoices."),
                ("key", "Administrator account", "The first login, with full access to everything."),
                ("percent", "Rates & taxes", "Currency, taxes and check-in / check-out times."),
                ("bed", "Rooms", "Room types with nightly rates, and your room numbers.")):
            row = QHBoxLayout()
            row.setSpacing(14)
            ic = QLabel()
            set_icon(ic, icon_name, "primary", 22)
            row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
            text_box = QVBoxLayout()
            text_box.setSpacing(0)
            text_box.addWidget(label(title, "h3"))
            text_box.addWidget(label(text, "muted"))
            row.addLayout(text_box, 1)
            card.body.addLayout(row)
        layout.addWidget(card)
        layout.addWidget(label(f"Your data is stored securely on this computer in:\n{paths.data_dir()}", "faint",
                               wrap=True, selectable=True))
        layout.addStretch(1)
        return page

    def _property(self) -> QWidget:
        page, layout = self._page("Your property", "This appears on invoices, receipts and the sign-in screen.")
        self.prop = FormGrid(2)
        self.prop.add("property.name", "Motel name", line("", "e.g. Sunset Motel", 100), required=True, span=2)
        self.prop.add("property.address1", "Street address", line(max_len=120), span=2)
        self.prop.add("property.city", "City", line(max_len=80))
        self.prop.add("property.state", "State / province", line(max_len=60))
        self.prop.add("property.postal_code", "Postal code", line(max_len=20))
        self.prop.add("property.country", "Country", line("", "", 60))
        self.prop.add("property.phone", "Phone", line(max_len=30))
        self.prop.add("property.email", "Email", line(max_len=120))
        layout.addWidget(self.prop)
        layout.addStretch(1)
        return page

    def _admin(self) -> QWidget:
        page, layout = self._page("Administrator account", "This account can configure everything, manage staff and "
                                  "restore backups. Create separate accounts for other staff later.")
        self.admin = FormGrid(2)
        self.admin.add("full_name", "Your name", line(max_len=100), required=True)
        self.admin.add("username", "Username", line("admin", "", 32), required=True)
        self.admin.add("password", "Password", password_field("At least 8 characters, letters and numbers"),
                       required=True)
        self.admin.add("confirm", "Confirm password", password_field(), required=True)
        self.admin.add("email", "Email (optional)", line(max_len=254), span=2)
        layout.addWidget(self.admin)
        layout.addWidget(Banner("Keep this password safe. If every administrator password is lost, data can only be "
                                "recovered from a backup file.", "info"))
        layout.addStretch(1)
        return page

    def _rates(self) -> QWidget:
        page, layout = self._page("Rates & policies", "Pick your currency and the taxes your property charges.")
        self.rates = FormGrid(2)
        self.rates.add("currency", "Currency", combo([(f"{c} — {n}", c) for c, n, _, _ in COMMON_CURRENCIES],
                                                     "USD"), span=2)
        self.rates.add("tax_name", "Sales / lodging tax name", line("Sales tax", "", 60))
        self.rates.add("tax_rate", "Tax rate (%)", line("", "e.g. 8.5 — leave empty for none", 6))
        self.rates.add("nightly_tax_name", "Per-night tax name", line("Occupancy tax", "", 60))
        self.rates.add("nightly_tax", "Per-night amount", line("", "e.g. 2.00 — optional", 10))
        self.rates.add("check_in_time", "Check-in time", line("15:00", "HH:MM", 5))
        self.rates.add("check_out_time", "Check-out time", line("11:00", "HH:MM", 5))
        layout.addWidget(self.rates)
        layout.addStretch(1)
        return page

    def _table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(36)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _types(self) -> QWidget:
        page, layout = self._page("Room types", "Group rooms that share a standard nightly rate. Double-click a cell "
                                  "to edit. Rooms can override the rate later.")
        self.types = self._table(["Code", "Name", "Beds", "Sleeps", "Nightly rate"])
        for rt in DEFAULT_ROOM_TYPES:
            self._add_type(rt["code"], rt["name"], rt["beds"], str(rt["max_occupancy"]), rt["base_rate"])
        layout.addWidget(self.types, 1)
        row = QHBoxLayout()
        row.addWidget(button("Add room type", "plus", "soft", on_click=lambda: self._add_type("", "", "", "2", "")))
        row.addWidget(button("Remove selected", "trash", "ghost",
                             on_click=lambda: self.types.removeRow(self.types.currentRow())
                             if self.types.currentRow() >= 0 else None))
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _add_type(self, *values: str) -> None:
        r = self.types.rowCount()
        self.types.insertRow(r)
        for c, v in enumerate(values):
            self.types.setItem(r, c, QTableWidgetItem(v))

    def _rooms(self) -> QWidget:
        page, layout = self._page("Rooms", "List your room numbers. Use the generator for a run of rooms, then "
                                  "edit or remove individual rows.")
        gen = Card(padding=14)
        g_host, g = toolbar(14)  # wraps on small screens instead of squeezing the fields
        self.gen_first = spin(101, 1, 99999)
        self.gen_count = spin(10, 1, 200)
        self.gen_type = combo([])
        self.gen_floor = line("1", "Floor", 10)
        self.gen_floor.setMaximumWidth(80)
        for text, w in (("First number", self.gen_first), ("How many", self.gen_count), ("Type", self.gen_type),
                        ("Floor", self.gen_floor)):
            pair = QWidget()
            pair.setObjectName("Transparent")
            pl = QHBoxLayout(pair)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(6)
            pl.addWidget(label(text, "label"))
            pl.addWidget(w)
            g.addWidget(pair)
        g.addWidget(button("Add rooms", "plus", "soft", on_click=self._generate))
        gen.body.addWidget(g_host)
        layout.addWidget(gen)
        self.rooms_table = self._table(["Room number", "Type code", "Floor"])
        for room in DEFAULT_ROOMS:
            self._add_room(room["number"], room["type_code"], room["floor"])
        layout.addWidget(self.rooms_table, 1)
        row = QHBoxLayout()
        self.rooms_count = label("", "faint")
        row.addWidget(self.rooms_count)
        row.addStretch(1)
        row.addWidget(button("Remove selected", "trash", "ghost", on_click=self._remove_rooms))
        row.addWidget(button("Clear all", "x", "ghost", on_click=lambda: (self.rooms_table.setRowCount(0),
                                                                          self._count_rooms())))
        layout.addLayout(row)
        self._count_rooms()
        return page

    def _add_room(self, number: str, code: str, floor: str) -> None:
        r = self.rooms_table.rowCount()
        self.rooms_table.insertRow(r)
        for c, v in enumerate((number, code, floor)):
            self.rooms_table.setItem(r, c, QTableWidgetItem(v))

    def _generate(self) -> None:
        existing = {self._cell(self.rooms_table, r, 0).upper() for r in range(self.rooms_table.rowCount())}
        added = 0
        for i in range(self.gen_count.value()):
            number = str(self.gen_first.value() + i)
            if number in existing:
                continue
            self._add_room(number, self.gen_type.currentData() or "", self.gen_floor.text().strip())
            added += 1
        self._count_rooms()
        if added < self.gen_count.value():
            self.banner.set(f"{self.gen_count.value() - added} room number(s) already existed and were skipped.",
                            "warning")

    def _remove_rooms(self) -> None:
        rows = sorted({i.row() for i in self.rooms_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.rooms_table.removeRow(r)
        self._count_rooms()

    def _count_rooms(self) -> None:
        self.rooms_count.setText(f"{self.rooms_table.rowCount()} room(s)")

    def _finish(self) -> QWidget:
        page, layout = self._page("Ready to go", "Review the summary and finish. You'll be signed in as the "
                                  "administrator and taken to the dashboard.")
        self.summary = label("", wrap=True)
        card = Card(padding=18)
        card.body.addWidget(self.summary)
        layout.addWidget(card)
        self.demo = QCheckBox("Load sample guests, reservations and history so I can explore the system")
        layout.addWidget(self.demo)
        layout.addWidget(label("Sample data is useful for training. Start with a fresh database for real use "
                               "(Settings › Backup & restore lets you keep a copy).", "faint", wrap=True))
        self.dark = QCheckBox("Use the dark theme")
        layout.addWidget(self.dark)
        layout.addStretch(1)
        return page

    # -- navigation ----------------------------------------------------------------------------------------------
    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.banner.hide()
        for i, lbl in enumerate(self.step_labels):
            state = "current" if i == index else ("done" if i < index else "todo")
            lbl.setProperty("step", state)
            lbl.setText(f"{'✓' if i < index else str(i + 1) + '.'}  {STEPS[i]}")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
        self.back_btn.setVisible(index > 0)
        self.next_btn.setText("Finish setup" if index == len(STEPS) - 1 else ("Get started" if index == 0
                                                                               else "Continue"))
        if index == 5:
            self.gen_type.clear()
            for r in range(self.types.rowCount()):
                code = self._cell(self.types, r, 0).upper()
                if code:
                    self.gen_type.addItem(f"{code} — {self._cell(self.types, r, 1)}", code)
        if index == len(STEPS) - 1:
            self._update_summary()

    def _back(self) -> None:
        self._go(max(self.stack.currentIndex() - 1, 0))

    def _next(self) -> None:
        index = self.stack.currentIndex()
        try:
            self._validate(index)
        except ValidationError as exc:
            form = {1: self.prop, 2: self.admin, 3: self.rates}.get(index)
            if form and form.set_errors(exc.field_errors):
                self.banner.set("Please correct the highlighted fields.", "error")
            else:
                self.banner.set(exc.message, "error")
            return
        if index == len(STEPS) - 1:
            self._complete()
        else:
            self._go(index + 1)

    @staticmethod
    def _cell(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text().strip() if item else ""

    def _room_types(self) -> list[dict]:
        out = []
        for r in range(self.types.rowCount()):
            values = [self._cell(self.types, r, c) for c in range(5)]
            if not any(values):
                continue
            out.append({"code": values[0], "name": values[1], "beds": values[2], "max_occupancy": values[3] or "2",
                        "base_rate": values[4]})
        return out

    def _room_list(self) -> list[dict]:
        out = []
        for r in range(self.rooms_table.rowCount()):
            number = self._cell(self.rooms_table, r, 0)
            if number:
                out.append({"number": number, "type_code": self._cell(self.rooms_table, r, 1).upper(),
                            "floor": self._cell(self.rooms_table, r, 2)})
        return out

    def _validate(self, index: int) -> None:
        if index == 1:
            self.prop.clear_errors()
            if not self.prop.values()["property.name"]:
                raise ValidationError("Motel name is required.", field="property.name")
        elif index == 2:
            self.admin.clear_errors()
            self.service.validate_admin(self.admin.values())
        elif index == 3:
            self.rates.clear_errors()
            from motelmg.core.dates import parse_time
            from motelmg.core.money import parse_percent
            v = self.rates.values()
            if v["tax_rate"]:
                parse_percent(v["tax_rate"], field="tax_rate", label="Tax rate", maximum=50)
            if v["nightly_tax"]:
                parse_amount(v["nightly_tax"], field="nightly_tax", label="Per-night tax")
            parse_time(v["check_in_time"], field="check_in_time", label="Check-in time")
            parse_time(v["check_out_time"], field="check_out_time", label="Check-out time")
        elif index == 4:
            types = self._room_types()
            if not types:
                raise ValidationError("Add at least one room type.")
            codes = set()
            for rt in types:
                if not rt["code"] or not rt["name"]:
                    raise ValidationError("Every room type needs a code and a name.")
                if rt["code"].upper() in codes:
                    raise ValidationError(f"Room type code {rt['code']} is used twice.")
                codes.add(rt["code"].upper())
                parse_amount(rt["base_rate"], label=f"Rate for {rt['name']}", allow_zero=False)
                if not rt["max_occupancy"].isdigit() or not 1 <= int(rt["max_occupancy"]) <= 20:
                    raise ValidationError(f"'Sleeps' for {rt['name']} must be a number from 1 to 20.")
        elif index == 5:
            rooms = self._room_list()
            if not rooms:
                raise ValidationError("Add at least one room.")
            codes = {rt["code"].upper() for rt in self._room_types()}
            seen = set()
            for room in rooms:
                if room["type_code"] not in codes:
                    raise ValidationError(f"Room {room['number']} has an unknown type code "
                                          f"'{room['type_code']}'. Use one of: {', '.join(sorted(codes))}.")
                if room["number"].upper() in seen:
                    raise ValidationError(f"Room {room['number']} is listed twice.")
                seen.add(room["number"].upper())

    def _update_summary(self) -> None:
        p = self.prop.values()
        r = self.rates.values()
        types = self._room_types()
        rooms = self._room_list()
        tax = f"{r['tax_name']} {r['tax_rate']}%" if r["tax_rate"] else "no percentage tax"
        if r["nightly_tax"]:
            tax += f" + {r['nightly_tax_name']} {r['nightly_tax']} per night"
        self.summary.setText(
            f"<b>{p['property.name']}</b>{' · ' + p['property.city'] if p['property.city'] else ''}<br>"
            f"Administrator: <b>{self.admin.values()['username']}</b><br>"
            f"Currency: {r['currency']} · Taxes: {tax}<br>"
            f"Check-in {r['check_in_time']} · check-out {r['check_out_time']}<br>"
            f"{len(types)} room type(s): {', '.join(t['name'] for t in types)}<br>"
            f"{len(rooms)} room(s)")

    def _complete(self) -> None:
        r = self.rates.values()
        data = {
            "property": self.prop.values(), "admin": self.admin.values(), "currency": r["currency"],
            "tax_name": r["tax_name"], "tax_rate": r["tax_rate"], "nightly_tax_name": r["nightly_tax_name"],
            "nightly_tax": r["nightly_tax"], "check_in_time": r["check_in_time"],
            "check_out_time": r["check_out_time"], "room_types": self._room_types(), "rooms": self._room_list(),
            "demo": self.demo.isChecked(), "theme": "dark" if self.dark.isChecked() else "light",
        }
        self.next_btn.setEnabled(False)
        self.overlay.start("Creating demo data…" if data["demo"] else "Setting things up…")
        QApplication.processEvents()
        try:
            self.service.complete(data)
        except MotelError as exc:
            self.overlay.stop()
            self.next_btn.setEnabled(True)
            self.banner.set(exc.message, "error")
            return
        except Exception as exc:  # noqa: BLE001
            self.overlay.stop()
            self.next_btn.setEnabled(True)
            from motelmg.ui.widgets.dialogs import show_error
            show_error(self, exc)
            return
        self.overlay.stop()
        self.accept()
