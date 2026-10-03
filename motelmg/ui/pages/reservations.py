from __future__ import annotations

from datetime import timedelta

from PySide6.QtWidgets import QCheckBox, QHBoxLayout

from motelmg.core.enums import ReservationSource, ReservationStatus as RS
from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.common import ChipGroup, SearchField, button, label
from motelmg.ui.widgets.date_range import DateRangePicker
from motelmg.ui.widgets.forms import combo
from motelmg.ui.widgets.table import Column, DataTable

PRESETS = [
    ("Arrivals today", "arrivals"), ("In house", "in_house"), ("Departures today", "departures"),
    ("Upcoming", "upcoming"), ("Past stays", "past"), ("Cancelled / no-show", "cancelled"), ("All", "all"),
]


class ReservationsPage(Page):
    key = "reservations"
    title = "Reservations"
    icon = "book"
    permission = "reservations.view"
    topics = ("reservations", "billing", "guests")

    def __init__(self, app):
        super().__init__(app)
        L = self.layout_
        top = QHBoxLayout()
        top.setSpacing(10)
        self.chips = ChipGroup(PRESETS)
        self.chips.set_current("upcoming")
        self.chips.changed.connect(lambda *_: self._preset_changed())
        top.addWidget(self.chips)
        top.addStretch(1)
        if self.ctx.can("reservations.create"):
            top.addWidget(button("New reservation", "plus", "primary", on_click=lambda: self.actions.new_reservation()))
        L.addLayout(top)
        filters = QHBoxLayout()
        filters.setSpacing(10)
        self.search = SearchField("Guest, confirmation #, room, phone…")
        self.search.search.connect(lambda *_: self.mark_stale())
        filters.addWidget(self.search, 1)
        self.use_dates = QCheckBox("Arrival between")
        self.use_dates.toggled.connect(lambda *_: self.mark_stale())
        filters.addWidget(self.use_dates)
        self.range = DateRangePicker(self.ctx.clock.today(), "next30")
        self.range.changed.connect(lambda *_: (self.use_dates.setChecked(True), self.mark_stale()))
        filters.addWidget(self.range)
        self.source = combo([("All sources", "")] + [(v, k) for k, v in ReservationSource.LABELS.items()])
        self.source.currentIndexChanged.connect(lambda *_: self.mark_stale())
        filters.addWidget(self.source)
        filters.addWidget(button("Export", "download", on_click=lambda: self.export_table(self.table, "reservations")))
        L.addLayout(filters)
        fmt = self.fmt
        self.table = DataTable([
            Column("confirmation_no", "Conf. #", width=86, bold=True),
            Column("guest_name", "Guest", stretch=True),
            Column("room_number", "Room", width=64),
            Column("room_type_name", "Type", width=130),
            Column("check_in_date", "Arrival", "date", width=112),
            Column("check_out_date", "Departure", "date", width=112),
            Column("nights", "Nights", "int", width=60),
            Column("guests", "Guests", "int", width=60),
            Column("status", "Status", "badge", width=118, fmt=lambda r: r["status_label"], tone=lambda r: r["tone"]),
            Column("total", "Total", "money", width=100),
            Column("balance", "Balance", "money", width=96),
            Column("source", "Source", width=100, fmt=lambda r: ReservationSource.LABELS.get(r["source"], r["source"])),
        ], fmt, empty_icon="book", empty_title="No reservations found",
            empty_text="Adjust the filters or create a new reservation.")
        self.table.activated.connect(lambda r: self.actions.open_reservation(r["id"]))
        self.table.set_menu_builder(self._menu)
        L.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        self.summary = label("", "faint")
        bottom.addWidget(self.summary)
        bottom.addStretch(1)
        self.action_btns = []
        for text, icon, fn, perm in (("Open", "book", self._open, None),
                                     ("Check in", "log-in", self._check_in, "reservations.checkin"),
                                     ("Check out", "log-out", self._check_out, "reservations.checkout"),
                                     ("Payment", "dollar", self._payment, "billing.payment")):
            if perm and not self.ctx.can(perm):
                continue
            b = button(text, icon, small=True, on_click=fn)
            bottom.addWidget(b)
            self.action_btns.append((text, b))
        L.addLayout(bottom)
        self.table.selection_changed.connect(self._update_buttons)
        self._update_buttons()

    def subtitle(self) -> str:
        return "Find, create and manage bookings"

    def on_show(self, **kwargs) -> None:
        if kwargs.get("preset"):
            self.chips.set_current(kwargs["preset"])
            self.use_dates.setChecked(False)
            self._stale = True
        super().on_show(**kwargs)

    def _preset_changed(self) -> None:
        self.use_dates.setChecked(False)
        self.mark_stale()

    def refresh(self) -> None:
        today = self.ctx.clock.today()
        preset = self.chips.current()
        args: dict = {"text": self.search.text().strip(), "source": self.source.currentData() or ""}
        order = "r.check_in_date ASC, rm.number"
        if preset == "arrivals":
            rows = self.ctx.reservations.arrivals(today)
        elif preset == "departures":
            rows = self.ctx.reservations.departures(today)
        else:
            if preset == "in_house":
                args["statuses"] = [RS.CHECKED_IN]
            elif preset == "upcoming":
                args["statuses"] = [RS.CONFIRMED]
            elif preset == "past":
                args["statuses"] = [RS.CHECKED_OUT]
                order = "r.check_out_date DESC"
            elif preset == "cancelled":
                args["statuses"] = [RS.CANCELLED, RS.NO_SHOW]
                order = "r.check_in_date DESC"
            else:
                order = "r.check_in_date DESC"
            if self.use_dates.isChecked():
                start, end = self.range.value()
                args["arrival_from"], args["arrival_to"] = start, end
            rows = self.ctx.reservations.search(order=order, **args)
        if preset in ("arrivals", "departures"):
            text = args["text"].lower()
            rows = [r for r in rows if not text or text in f"{r.guest_name} {r.confirmation_no} {r.room_number}".lower()]
        out = []
        for r in rows:
            overdue = r.status == RS.CHECKED_IN and self.ctx.reservations.is_overdue(r)
            late = r.status == RS.CONFIRMED and r.check_in_date < today
            status_label = "Overdue" if overdue else ("Late arrival" if late else RS.LABELS[r.status])
            tone = "red" if overdue else ("orange" if late else RS.TONES[r.status])
            total = self.ctx.billing.estimate(r)
            out.append({"id": r.id, "confirmation_no": r.confirmation_no,
                        "guest_name": r.guest_name + (" ★" if r.guest_is_vip else ""),
                        "room_number": r.room_number, "room_type_name": r.room_type_name,
                        "check_in_date": r.check_in_date, "check_out_date": r.check_out_date, "nights": r.nights,
                        "guests": r.guests_count, "status": r.status, "status_label": status_label, "tone": tone,
                        "total": total, "balance": (total - r.paid) if r.status == RS.CONFIRMED else r.balance,
                        "source": r.source})
        self.table.set_rows(out)
        value = sum(r["total"] for r in out if r["status"] not in (RS.CANCELLED, RS.NO_SHOW))
        self.summary.setText(f"{len(out)} reservation(s) · {self.fmt.money(value)} total value")
        self._update_buttons()
        if today:
            pass

    # -- actions -----------------------------------------------------------------------------------------
    def _menu(self, row) -> list:
        res_id, status, can = row["id"], row["status"], self.ctx.can
        entries = [("Open", lambda: self.actions.open_reservation(res_id))]
        if status == RS.CONFIRMED:
            entries += [("Check in…", lambda: self.actions.check_in(res_id), can("reservations.checkin")),
                        ("Modify…", lambda: self.actions.edit_reservation(res_id), can("reservations.edit")),
                        ("Change room…", lambda: self.actions.transfer(res_id), can("reservations.transfer")),
                        ("Record deposit…", lambda: self.actions.take_payment(res_id), can("billing.payment")),
                        None,
                        ("Cancel reservation…", lambda: self.actions.cancel(res_id), can("reservations.cancel")),
                        ("Mark no-show…", lambda: self.actions.cancel(res_id, no_show=True),
                         can("reservations.cancel") and row["check_in_date"] <= self.ctx.clock.today())]
        elif status == RS.CHECKED_IN:
            entries += [("Check out…", lambda: self.actions.check_out(res_id), can("reservations.checkout")),
                        ("Take payment…", lambda: self.actions.take_payment(res_id), can("billing.payment")),
                        ("Add charge…", lambda: self.actions.add_charge(res_id), can("billing.charge")),
                        ("Move room…", lambda: self.actions.transfer(res_id), can("reservations.transfer")),
                        ("Modify stay…", lambda: self.actions.edit_reservation(res_id), can("reservations.edit"))]
        else:
            entries += [("Take payment…", lambda: self.actions.take_payment(res_id),
                         can("billing.payment") and row["balance"] > 0)]
        entries += [None, ("Print folio…", lambda: self.actions.print_folio(res_id))]
        return entries

    def _update_buttons(self) -> None:
        row = self.table.selected_row()
        status = row["status"] if row else None
        for text, b in self.action_btns:
            enabled = row is not None
            if text == "Check in":
                enabled = status == RS.CONFIRMED and row["check_out_date"] > self.ctx.clock.today()
            elif text == "Check out":
                enabled = status == RS.CHECKED_IN
            elif text == "Payment":
                enabled = row is not None and status not in (RS.CANCELLED, RS.NO_SHOW) or bool(row and row["balance"] > 0)
            b.setEnabled(bool(enabled))

    def _selected(self):
        return self.table.selected_row()

    def _open(self) -> None:
        if row := self._selected():
            self.actions.open_reservation(row["id"])

    def _check_in(self) -> None:
        if row := self._selected():
            self.actions.check_in(row["id"])

    def _check_out(self) -> None:
        if row := self._selected():
            self.actions.check_out(row["id"])

    def _payment(self) -> None:
        if row := self._selected():
            self.actions.take_payment(row["id"])


__all__ = ["ReservationsPage", "timedelta"]
