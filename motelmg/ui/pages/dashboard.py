from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from motelmg.core.enums import ReservationStatus, RoomState
from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.charts import BarChart, DonutChart
from motelmg.ui.widgets.common import Card, CardGrid, EmptyState, StatCard, button, clear_layout, label, set_icon
from motelmg.ui.widgets.table import Column, DataTable

SEVERITY = {"critical": ("alert-circle", "red"), "warning": ("alert", "amber"), "info": ("info", "blue")}


def quick_button(text: str, icon_name: str, on_click) -> QPushButton:
    btn = QPushButton(f"  {text}")
    btn.setProperty("quick", True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    set_icon(btn, icon_name, "primary", 18)
    btn.clicked.connect(lambda *_: on_click())
    return btn


class DashboardPage(Page):
    key = "dashboard"
    title = "Dashboard"
    icon = "home"
    permission = "dashboard.view"
    topics = ("reservations", "rooms", "billing", "housekeeping", "maintenance", "alerts", "settings")
    scrollable = True

    def __init__(self, app):
        super().__init__(app)
        ctx = self.ctx
        L = self.layout_
        # greeting + quick actions
        head = QHBoxLayout()
        head.setSpacing(10)
        greet = QVBoxLayout()
        greet.setSpacing(2)
        self.greeting = label("", "h1")
        self.greeting_sub = label("", "muted")
        greet.addWidget(self.greeting)
        greet.addWidget(self.greeting_sub)
        head.addLayout(greet, 1)
        L.addLayout(head)
        quick = QHBoxLayout()
        quick.setSpacing(10)
        if ctx.can("reservations.create"):
            quick.addWidget(quick_button("New reservation", "calendar", lambda: self.actions.new_reservation()))
            if ctx.can("reservations.checkin"):
                quick.addWidget(quick_button("Walk-in", "log-in", lambda: self.actions.walk_in()))
        if ctx.can("reservations.checkin"):
            quick.addWidget(quick_button("Check in", "door", self._quick_check_in))
        if ctx.can("reservations.checkout"):
            quick.addWidget(quick_button("Check out", "log-out", self._quick_check_out))
        if ctx.can("guests.edit"):
            quick.addWidget(quick_button("New guest", "user-plus", lambda: self.actions.new_guest()))
        quick.addWidget(quick_button("Find anything", "search", lambda: self.actions.search()))
        quick.addStretch(1)
        L.addLayout(quick)

        # KPI tiles
        self.k_occ = StatCard("OCCUPANCY", "activity", "blue")
        self.k_avail = StatCard("READY TO SELL", "check-circle", "green")
        self.k_arr = StatCard("ARRIVALS TODAY", "log-in", "purple")
        self.k_dep = StatCard("DEPARTURES TODAY", "log-out", "indigo")
        self.k_dirty = StatCard("NEEDS CLEANING", "sparkles", "amber")
        self.k_ooo = StatCard("OUT OF ORDER", "tool", "orange")
        tiles = [self.k_occ, self.k_avail, self.k_arr, self.k_dep, self.k_dirty, self.k_ooo]
        kpis = CardGrid(tiles)  # three per row on small screens
        self.k_occ.clicked.connect(lambda: app.navigate("rooms"))
        self.k_avail.clicked.connect(lambda: app.navigate("rooms", filter=RoomState.AVAILABLE))
        self.k_arr.clicked.connect(lambda: app.navigate("reservations", preset="arrivals"))
        self.k_dep.clicked.connect(lambda: app.navigate("reservations", preset="departures"))
        self.k_dirty.clicked.connect(lambda: app.navigate("housekeeping"))
        self.k_ooo.clicked.connect(lambda: app.navigate("maintenance"))
        L.addWidget(kpis)
        self.financial = ctx.can("reports.financial") or ctx.can("billing.view")
        if self.financial:
            fin = QGridLayout()
            fin.setSpacing(14)
            self.k_rev = StatCard("REVENUE TODAY", "dollar", "green")
            self.k_mtd = StatCard("REVENUE MONTH TO DATE", "trending", "teal")
            self.k_col = StatCard("COLLECTED TODAY", "card", "blue")
            self.k_out = StatCard("OUTSTANDING BALANCES", "receipt", "red")
            for i, tile in enumerate((self.k_rev, self.k_mtd, self.k_col, self.k_out)):
                fin.addWidget(tile, 0, i)
            self.k_out.clicked.connect(lambda: app.navigate("billing", tab="outstanding"))
            self.k_col.clicked.connect(lambda: app.navigate("billing"))
            if ctx.can("reports.view"):
                self.k_mtd.clicked.connect(lambda: app.navigate("reports"))
            L.addLayout(fin)

        # main grid
        grid = QHBoxLayout()
        grid.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        right = QVBoxLayout()
        right.setSpacing(16)
        grid.addLayout(left, 3)
        grid.addLayout(right, 2)
        L.addLayout(grid)

        res_cols = lambda kind: [  # noqa: E731
            Column("room_number", "Room", width=64, bold=True),
            Column("guest_name", "Guest", stretch=True),
            Column("nights", "Nights", "int", width=60),
            Column("info", "Due" if kind == "dep" else "ETA", width=90),
            Column("balance", "Balance", "money", width=96),
            Column("status", "Status", "badge", width=112, fmt=lambda r: r["status_label"], tone=lambda r: r["tone"]),
        ]
        self.arrivals_card = Card("Today's arrivals", icon_name="log-in")
        self.arrivals = DataTable(res_cols("arr"), self.fmt, empty_icon="log-in", empty_title="No arrivals today",
                                  empty_text="Reservations arriving today will appear here.", row_height=36)
        self.arrivals.activated.connect(lambda r: self._arrival_action(r))
        self.arrivals.set_menu_builder(self._res_menu)
        self.arrivals_card.body.addWidget(self.arrivals)
        self.arrivals_card.add_action(button("View all", variant="link",
                                             on_click=lambda: app.navigate("reservations", preset="arrivals")))
        left.addWidget(self.arrivals_card)
        self.departures_card = Card("Today's departures", icon_name="log-out")
        self.departures = DataTable(res_cols("dep"), self.fmt, empty_icon="log-out", empty_title="No departures today",
                                    row_height=36)
        self.departures.activated.connect(lambda r: self._departure_action(r))
        self.departures.set_menu_builder(self._res_menu)
        self.departures_card.body.addWidget(self.departures)
        self.departures_card.add_action(button("View all", variant="link",
                                               on_click=lambda: app.navigate("reservations", preset="departures")))
        left.addWidget(self.departures_card)
        self.upcoming_card = Card("Upcoming arrivals · next 7 days", icon_name="calendar")
        self.upcoming = DataTable([
            Column("check_in_date", "Arrival", width=110, fmt=lambda r: self.fmt.relative_day(r["check_in_date"])),
            Column("room_number", "Room", width=64, bold=True),
            Column("guest_name", "Guest", stretch=True),
            Column("nights", "Nights", "int", width=60),
            Column("confirmation_no", "Conf. #", width=90),
        ], self.fmt, empty_icon="calendar", empty_title="Nothing booked for the next week", row_height=34)
        self.upcoming.activated.connect(lambda r: self.actions.open_reservation(r["id"]))
        self.upcoming_card.body.addWidget(self.upcoming)
        left.addWidget(self.upcoming_card)
        left.addStretch(1)

        self.alerts_card = Card("Needs attention", icon_name="bell")
        self.alerts_box = QVBoxLayout()
        self.alerts_box.setSpacing(6)
        self.alerts_card.body.addLayout(self.alerts_box)
        right.addWidget(self.alerts_card)
        self.status_card = Card("Room status", icon_name="grid")
        self.donut = DonutChart(150)
        self.status_card.body.addWidget(self.donut)
        self.status_card.add_action(button("Open room board", variant="link", on_click=lambda: app.navigate("rooms")))
        right.addWidget(self.status_card)
        self.trend_card = Card("Occupancy · last 7 days", icon_name="trending")
        self.trend = BarChart(lambda v: f"{v:.0f}%", min_height=170)
        self.trend_card.body.addWidget(self.trend)
        right.addWidget(self.trend_card)
        right.addStretch(1)

    def subtitle(self) -> str:
        return f"{self.fmt.date(self.ctx.clock.today())} · {self.ctx.settings.property_name}"

    # -- refresh ------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        d = self.ctx.dashboard.data()
        fmt = self.fmt
        hour = self.ctx.clock.now().hour
        part = "morning" if hour < 12 else ("afternoon" if hour < 18 else "evening")
        name = self.ctx.session.full_name.split()[0] if self.ctx.session else ""
        self.greeting.setText(f"Good {part}, {name}")
        self.greeting_sub.setText(f"{fmt.date(d.today)} · {d.in_house_guests} guest(s) in house · "
                                  f"{d.total_rooms} rooms")
        sellable = d.total_rooms - d.out_of_order
        self.k_occ.set(f"{d.occupancy_pct:.0f}%", f"{d.occupied} of {sellable} sellable rooms occupied")
        self.k_avail.set(str(d.available), "vacant, clean and in service")
        self.k_arr.set(str(d.arrivals_total), f"{d.arrivals_pending} still to check in" if d.arrivals_pending
                       else "all checked in" if d.arrivals_total else "no arrivals")
        self.k_dep.set(str(d.departures_total), f"{d.departures_pending} still to check out" if d.departures_pending
                       else "all checked out" if d.departures_total else "no departures")
        self.k_dirty.set(str(d.vacant_dirty), "vacant rooms not yet ready", "amber" if d.vacant_dirty else "green")
        self.k_ooo.set(str(d.out_of_order), "maintenance / out of service", "orange" if d.out_of_order else "gray")
        if self.financial:
            self.k_rev.set(fmt.money(d.revenue_today), "charges posted today")
            self.k_mtd.set(fmt.money(d.revenue_mtd), d.today.strftime("since %b 1"))
            self.k_col.set(fmt.money(d.collected_today), "payments less refunds")
            self.k_out.set(fmt.money(d.outstanding_total), f"{d.outstanding_count} folio(s) with a balance",
                           "red" if d.outstanding_total else "green")

        def row(r, kind):
            overdue = kind == "dep" and r.status == "checked_in" and self.ctx.reservations.is_overdue(r)
            if kind == "arr":
                label_, tone = (("Arrived", "green") if r.status != "confirmed" else
                                ("Late" if r.check_in_date < d.today else "Expected", "purple"))
                info = fmt.time(r.expected_arrival) if r.expected_arrival else ("—" if r.check_in_date == d.today
                                                                               else fmt.short_date(r.check_in_date))
            else:
                label_, tone = (("Overdue", "red") if overdue else ("In house", "blue")) if r.status == "checked_in" \
                    else ("Departed", "gray")
                info = fmt.time(r.late_checkout_until) if r.late_checkout_until else \
                    fmt.time(self.ctx.settings.check_out_time())
            balance = r.balance if r.status != "confirmed" else self.ctx.billing.estimate(r) - r.paid
            return {"id": r.id, "room_number": r.room_number, "guest_name": r.guest_name + (" ★" if r.guest_is_vip
                                                                                          else ""),
                    "nights": r.nights, "info": info, "balance": balance, "status": r.status,
                    "status_label": label_, "tone": tone}

        arrivals = [row(r, "arr") for r in d.arrivals]
        departures = [row(r, "dep") for r in d.departures]
        self.arrivals.set_rows(arrivals)
        self.departures.set_rows(departures)
        for table, rows in ((self.arrivals, arrivals), (self.departures, departures)):
            table.setFixedHeight(min(max(len(rows), 1) * 36 + 44, 300) if rows else 190)
        self.upcoming.set_rows([{"id": r.id, "check_in_date": r.check_in_date, "room_number": r.room_number,
                                 "guest_name": r.guest_name, "nights": r.nights, "confirmation_no": r.confirmation_no}
                                for r in d.upcoming])
        self.upcoming.setFixedHeight(min(max(len(d.upcoming), 1) * 34 + 44, 290) if d.upcoming else 170)
        self.arrivals_card.set_title(f"Today's arrivals ({d.arrivals_pending} pending)")
        self.departures_card.set_title(f"Today's departures ({d.departures_pending} pending)")
        self._refresh_alerts()
        counts = d.state_counts
        self.donut.set_data([
            ("Ready", counts.get(RoomState.AVAILABLE, 0), "green"),
            ("Occupied", counts.get(RoomState.OCCUPIED, 0) + counts.get(RoomState.DUE_OUT, 0), "blue"),
            ("Overdue", counts.get(RoomState.OVERDUE, 0), "red"),
            ("Arriving", counts.get(RoomState.RESERVED, 0), "purple"),
            ("Needs cleaning", counts.get(RoomState.VACANT_DIRTY, 0), "amber"),
            ("Out of order", d.out_of_order, "orange"),
        ], f"{d.occupancy_pct:.0f}%", "occupied")
        self.trend.set_data([lbl for lbl, _ in d.occupancy_7d], [("Occupancy", [v for _, v in d.occupancy_7d])])

    def _refresh_alerts(self) -> None:
        clear_layout(self.alerts_box)
        alerts = self.ctx.alerts.current()
        if not alerts:
            self.alerts_box.addWidget(EmptyState("check-circle", "All clear", "No alerts right now.", compact=True))
            return
        for alert in alerts[:7]:
            self.alerts_box.addWidget(self._alert_row(alert))
        if len(alerts) > 7:
            more = button(f"View all {len(alerts)} alerts", variant="link", on_click=self.app._show_alerts)
            self.alerts_box.addWidget(more)

    def _alert_row(self, alert) -> QWidget:
        row = QFrame()
        row.setProperty("soft", True)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        ic = QLabel()
        name, tone = SEVERITY.get(alert.severity, SEVERITY["info"])
        set_icon(ic, name, tone, 17)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(alert.title, "h3"))
        msg = label(alert.message, "faint", wrap=True)
        text.addWidget(msg)
        lay.addLayout(text, 1)
        row.mouseReleaseEvent = lambda e, a=alert: self.actions.open_alert(a)  # type: ignore[assignment]
        return row

    # -- actions ------------------------------------------------------------------------------------------
    def _res_menu(self, row) -> list:
        res_id = row["id"]
        status = row["status"]
        can = self.ctx.can
        entries = [("Open reservation", lambda: self.actions.open_reservation(res_id))]
        if status == ReservationStatus.CONFIRMED:
            entries.append(("Check in…", lambda: self.actions.check_in(res_id), can("reservations.checkin")))
        if status == ReservationStatus.CHECKED_IN:
            entries.append(("Check out…", lambda: self.actions.check_out(res_id), can("reservations.checkout")))
            entries.append(("Take payment…", lambda: self.actions.take_payment(res_id), can("billing.payment")))
        return entries

    def _arrival_action(self, row) -> None:
        if row["status"] == ReservationStatus.CONFIRMED and self.ctx.can("reservations.checkin"):
            self.actions.check_in(row["id"])
        else:
            self.actions.open_reservation(row["id"])

    def _departure_action(self, row) -> None:
        if row["status"] == ReservationStatus.CHECKED_IN and self.ctx.can("reservations.checkout"):
            self.actions.check_out(row["id"])
        else:
            self.actions.open_reservation(row["id"])

    def _quick_check_in(self) -> None:
        row = self.arrivals.selected_row()
        pending = [r for r in self.arrivals.rows() if r["status"] == ReservationStatus.CONFIRMED]
        if row and row["status"] == ReservationStatus.CONFIRMED:
            self.actions.check_in(row["id"])
        elif len(pending) == 1:
            self.actions.check_in(pending[0]["id"])
        else:
            self.app.navigate("reservations", preset="arrivals")
            self.app.toast("Select the arriving guest and press Check in", "info")

    def _quick_check_out(self) -> None:
        row = self.departures.selected_row()
        pending = [r for r in self.departures.rows() if r["status"] == ReservationStatus.CHECKED_IN]
        if row and row["status"] == ReservationStatus.CHECKED_IN:
            self.actions.check_out(row["id"])
        elif len(pending) == 1:
            self.actions.check_out(pending[0]["id"])
        else:
            self.app.navigate("reservations", preset="in_house")
            self.app.toast("Select the departing guest and press Check out", "info")
