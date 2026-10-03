"""New reservation / walk-in / modify reservation dialog with live
availability and price quote."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from motelmg.core.enums import HKStatus, ReservationSource, ReservationStatus
from motelmg.core.errors import MotelError
from motelmg.ui.widgets.common import clear_layout, Badge, Card, Divider, label
from motelmg.ui.widgets.dialogs import BaseDialog, confirm
from motelmg.ui.widgets.forms import (DateEdit, FormGrid, MoneyEdit, OptionalTimeEdit, combo, line, on_change, set_combo,
                                      spin, text_area)
from motelmg.ui.widgets.guest_picker import GuestPicker
from motelmg.ui.widgets.table import Column, DataTable


class ReservationDialog(BaseDialog):
    """``mode`` is ``new``, ``walk_in`` or ``edit``."""

    def __init__(self, parent, app, *, mode: str = "new", reservation_id: int | None = None,
                 guest_id: int | None = None, room_id: int | None = None, arrival: date | None = None,
                 nights: int = 1):
        self.app = app
        self.ctx = app.ctx
        self.mode = mode
        self.res = self.ctx.reservations.get(reservation_id) if reservation_id else None
        titles = {"new": ("New reservation", "Find the guest, pick dates and an available room."),
                  "walk_in": ("Walk-in check-in", "Register a guest arriving now and check them straight in."),
                  "edit": (f"Modify {self.res.confirmation_no}" if self.res else "Modify reservation",
                           self.res.guest_name if self.res else "")}
        title, subtitle = titles[mode]
        super().__init__(parent, title, subtitle, icon_name={"new": "calendar", "walk_in": "log-in",
                                                             "edit": "edit"}[mode],
                         tone="green" if mode == "walk_in" else "blue", width=1080)
        self.resize(1120, 760)
        self.result_value = None
        self.today = self.ctx.clock.today()
        self.in_house = bool(self.res and self.res.status == ReservationStatus.CHECKED_IN)
        self._room_id = room_id or (self.res.room_id if self.res else None)
        self._loading = True

        columns = QHBoxLayout()
        columns.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(14)
        columns.addLayout(left, 3)
        right = QVBoxLayout()
        right.setSpacing(12)
        columns.addLayout(right, 2)
        self.body.addLayout(columns, 1)

        # guest
        guest_card = Card("Guest", padding=14)
        self.guest = GuestPicker(app, guest_id or (self.res.guest_id if self.res else None),
                                 allow_change=not self.in_house)
        self.guest.changed.connect(lambda *_: self._update_summary())
        guest_card.body.addWidget(self.guest)
        left.addWidget(guest_card)

        # stay
        stay_card = Card("Stay", padding=14)
        self.stay = self.register_form(FormGrid(4))
        arrival = arrival or (self.res.check_in_date if self.res else self.today)
        n = self.res.nights if self.res else nights
        self.arrive = DateEdit(arrival)
        self.depart = DateEdit(arrival + timedelta(days=n))
        self.nights = spin(n, 1, self.ctx.settings.get_int("policy.max_nights"), " night(s)")
        self.adults = spin(self.res.adults if self.res else 1, 1, 20)
        self.children = spin(self.res.children if self.res else 0, 0, 20)
        if mode == "walk_in":
            self.stay.add("nights", "Nights", self.nights)
            self.stay.add("check_out_date", "Departure", self.depart)
            self.arrive.set_value(self.today)
        else:
            self.stay.add("check_in_date", "Arrival", self.arrive, required=True)
            self.stay.add("check_out_date", "Departure", self.depart, required=True)
            self.stay.add("nights", "Nights", self.nights)
        self.stay.add("adults", "Adults", self.adults)
        self.stay.add("children", "Children", self.children)
        if mode == "walk_in":
            self.depart.setEnabled(False)
        if self.in_house:
            self.arrive.setEnabled(False)
        stay_card.body.addWidget(self.stay)
        left.addWidget(stay_card)

        # rooms
        room_card = Card("Room", "Only rooms free for every night of the stay are listed.", padding=14)
        types = [("All room types", None)] + [(t.name, t.id) for t in self.ctx.rooms.list_types()]
        self.type_filter = combo(types)
        room_card.add_action(self.type_filter)
        self.rooms = DataTable([
            Column("number", "Room", width=70, bold=True),
            Column("type", "Type", stretch=True),
            Column("beds", "Beds", width=130),
            Column("capacity", "Sleeps", "int", width=60),
            Column("rate", "Rate", "money", width=90),
            Column("hk", "Status", "badge", width=110, fmt=lambda r: r["hk_label"], tone=lambda r: r["hk_tone"]),
        ], app.fmt, empty_icon="bed", empty_title="No rooms available",
            empty_text="Try different dates, fewer guests or another room type.", row_height=34)
        self.rooms.setMinimumHeight(190)
        self.rooms.selection_changed.connect(self._room_selected)
        room_card.body.addWidget(self.rooms)
        if self.in_house:
            room_card.body.addWidget(label("The guest is in house. Use 'Transfer room' on the reservation to move "
                                           "them to another room.", "faint", wrap=True))
            self.rooms.setEnabled(False)
            self.type_filter.setEnabled(False)
        left.addWidget(room_card, 1)

        # details (right column)
        details = Card("Rate & details", padding=14)
        self.details = self.register_form(FormGrid(2))
        self.rate = MoneyEdit()
        self.rate.setMaximumWidth(10_000)
        can_override = self.ctx.can("reservations.override_rate")
        self.rate.setReadOnly(not can_override)
        if not can_override:
            self.rate.setToolTip("Your role cannot change the standard rate.")
        self.details.add("nightly_rate", "Nightly rate", self.rate,
                         hint="" if can_override else "Standard rate for the room")
        discounts = [("No discount", None)] + [(f"{d.name} ({d.percent_bp / 100:g}%)", d.id)
                                               for d in self.ctx.catalog.discount_types()]
        self.discount = combo(discounts)
        self.details.add("discount_id", "Discount", self.discount)
        sources = [(v, k) for k, v in ReservationSource.LABELS.items() if k != "walk_in" or mode == "walk_in"]
        self.source = combo(sources, "walk_in" if mode == "walk_in" else (self.res.source if self.res else "phone"))
        self.details.add("source", "Booked via", self.source)
        if mode != "walk_in":
            self.eta = OptionalTimeEdit(self.res.expected_arrival if self.res else "")
            self.details.add("expected_arrival", "Expected arrival", self.eta)
        if self.in_house or mode == "edit":
            self.late = OptionalTimeEdit(self.res.late_checkout_until if self.res else "")
            self.details.add("late_checkout_until", "Late check-out until", self.late)
        self.requests = text_area(self.res.special_requests if self.res else "",
                                  "Requests the housekeeping/front desk should know", 54)
        self.details.add("special_requests", "Special requests", self.requests, span=2)
        if mode != "edit":
            self.note = text_area("", "Internal note (optional)", 44)
            self.details.add("note", "Note", self.note, span=2)
        details.body.addWidget(self.details)
        right.addWidget(details)

        # summary
        self.summary = Card("Summary", padding=14, spacing=6)
        self.summary_lines = QGridLayout()
        self.summary_lines.setHorizontalSpacing(10)
        self.summary_lines.setVerticalSpacing(5)
        self.summary.body.addLayout(self.summary_lines)
        right.addWidget(self.summary)

        # walk-in payment
        if mode == "walk_in":
            pay = Card("Payment now", padding=14)
            self.pay_form = self.register_form(FormGrid(2))
            self.pay_amount = MoneyEdit()
            self.pay_amount.setMaximumWidth(10_000)
            methods = [(m.name, m.id) for m in self.ctx.catalog.payment_methods()]
            self.pay_method = combo(methods)
            self.pay_ref = line(placeholder="Last 4 digits / check no.", max_len=60)
            self.pay_form.add("amount", "Amount", self.pay_amount, hint="Leave empty to collect later")
            self.pay_form.add("method_id", "Method", self.pay_method)
            self.pay_form.add("reference", "Reference", self.pay_ref, span=2)
            pay.body.addWidget(self.pay_form)
            pay.setEnabled(self.ctx.can("billing.payment"))
            right.addWidget(pay)
        right.addStretch(1)

        # defaults for editing
        if self.res:
            self.rate.set_cents(self.res.nightly_rate)
            if self.res.discount_name:
                for d in self.ctx.catalog.discount_types():
                    if d.name == self.res.discount_name:
                        set_combo(self.discount, d.id)

        # footer
        self.add_cancel()
        if mode == "walk_in":
            self.save_btn = self.add_footer_button("Check in now", self._save, "primary", icon_name="log-in",
                                                   default=True)
        else:
            self.save_btn = self.add_footer_button("Save changes" if mode == "edit" else "Create reservation",
                                                   self._save, "primary", icon_name="check", default=True)

        # wiring
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(120)
        self._refresh_timer.timeout.connect(self._refresh_rooms)
        self.arrive.dateChanged.connect(lambda *_: self._dates_changed("arrive"))
        self.depart.dateChanged.connect(lambda *_: self._dates_changed("depart"))
        self.nights.valueChanged.connect(lambda *_: self._dates_changed("nights"))
        for w in (self.adults, self.children, self.type_filter):
            on_change(w, self._refresh_timer.start)
        for w in (self.rate, self.discount):
            on_change(w, self._update_summary)
        self._loading = False
        self._refresh_rooms()
        if not self.guest.guest_id:
            self.guest.search.setFocus()

    # -- dates & rooms ------------------------------------------------------------------------------
    def _dates_changed(self, source: str) -> None:
        if self._loading:
            return
        self._loading = True
        if source == "nights" or self.mode == "walk_in":
            self.depart.set_value(self.arrive.value() + timedelta(days=self.nights.value()))
        elif source == "arrive":
            self.depart.set_value(self.arrive.value() + timedelta(days=self.nights.value()))
        else:
            nights = (self.depart.value() - self.arrive.value()).days
            if nights >= 1:
                self.nights.setValue(nights)
        self._loading = False
        self._refresh_timer.start()

    def _stay(self) -> tuple[date, date]:
        return self.arrive.value(), self.depart.value()

    def _refresh_rooms(self) -> None:
        ci, co = self._stay()
        rows = []
        if co > ci:
            available = self.ctx.rooms.available_rooms(
                ci, co, room_type_id=self.type_filter.currentData(),
                exclude_reservation=self.res.id if self.res else None,
                guests=self.adults.value() + self.children.value())
            for room in available:
                hk = room.hk_status
                ready = hk in (HKStatus.CLEAN, HKStatus.INSPECTED)
                show_hk = ci == self.today
                rows.append({"id": room.id, "number": room.number, "type": room.type_name,
                             "beds": room.effective_beds, "capacity": room.capacity, "rate": room.effective_rate,
                             "hk_label": HKStatus.LABELS[hk] if show_hk else "Available",
                             "hk_tone": ("green" if ready else "amber") if show_hk else "green", "room": room})
            if self.in_house and self.res:
                room = self.ctx.rooms.get(self.res.room_id)
                if not any(r["id"] == room.id for r in rows):
                    rows.insert(0, {"id": room.id, "number": room.number, "type": room.type_name,
                                    "beds": room.effective_beds, "capacity": room.capacity,
                                    "rate": room.effective_rate, "hk_label": "Current room", "hk_tone": "blue",
                                    "room": room})
        self.rooms.set_rows(rows, keep_selection=False)
        if self._room_id and not self.rooms.select_id(self._room_id):
            self._room_id = None if not self.in_house else self._room_id
        if not self._room_id and rows and self.mode != "edit":
            pass
        self._update_summary()

    def _room_selected(self) -> None:
        row = self.rooms.selected_row()
        if row is None:
            return
        changed = row["id"] != self._room_id
        self._room_id = row["id"]
        if changed and not (self.res and self.res.rate_overridden and row["id"] == self.res.room_id):
            if not (self.res and row["id"] == self.res.room_id):
                self.rate.set_cents(row["rate"])
            elif self.res:
                self.rate.set_cents(self.res.nightly_rate)
        if not self.rate.text():
            self.rate.set_cents(row["rate"])
        self._update_summary()

    # -- summary ---------------------------------------------------------------------------------
    def _clear_summary(self) -> None:
        clear_layout(self.summary_lines)

    def _line(self, row: int, text: str, value: str = "", role: str | None = None) -> None:
        a = label(text, role or "muted")
        b = label(value, role or "value")
        b.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.summary_lines.addWidget(a, row, 0)
        self.summary_lines.addWidget(b, row, 1)

    def _update_summary(self) -> None:
        if self._loading:
            return
        self._clear_summary()
        fmt = self.app.fmt
        ci, co = self._stay()
        r = 0
        if self._room_id is None:
            self.summary_lines.addWidget(label("Select a room to see the price.", "faint"), 0, 0, 1, 2)
            return
        room = self.ctx.rooms.get(self._room_id)
        self._line(r, "Room", f"{room.number} · {room.type_name}")
        r += 1
        self._line(r, "Dates", f"{fmt.short_date(ci)} → {fmt.short_date(co)}")
        r += 1
        try:
            quote = self.ctx.reservations.quote(room_id=room.id, check_in=ci, check_out=co,
                                                nightly_rate=self.rate.value() or None,
                                                discount_id=self.discount.currentData())
        except MotelError:
            self._line(r, "Enter a valid rate to see the total.", "")
            return
        for item in quote.lines:
            self._line(r, item.description.replace("rate", fmt.money(quote.nightly_rate)), fmt.money(item.amount))
            r += 1
        for tax in quote.taxes:
            self._line(r, tax.name, fmt.money(tax.amount))
            r += 1
        div = Divider()
        self.summary_lines.addWidget(div, r, 0, 1, 2)
        r += 1
        self._line(r, "Estimated total", fmt.money(quote.total), "h3")
        r += 1
        paid = self.ctx.repo_folio.paid_total(self.res.id) if self.res else 0
        if paid:
            self._line(r, "Paid so far", fmt.money(paid))
            r += 1
        if quote.deposit_suggested and self.mode == "new":
            self._line(r, "Suggested deposit", fmt.money(quote.deposit_suggested))
            r += 1
        if self.mode == "walk_in" and not self.pay_amount.text():
            self.pay_amount.set_cents(quote.total)
        if self.in_house:
            self._line(r, "Posted charges are adjusted when you save.", "", "faint")

    # -- save ------------------------------------------------------------------------------------------
    def _payload(self) -> dict:
        data = {
            "guest_id": self.guest.guest_id, "room_id": self._room_id,
            "check_in_date": self.arrive.value(), "check_out_date": self.depart.value(),
            "adults": self.adults.value(), "children": self.children.value(),
            "nightly_rate": self.rate.value(), "discount_id": self.discount.currentData(),
            "source": self.source.currentData(), "special_requests": self.requests.toPlainText(),
        }
        if hasattr(self, "eta"):
            data["expected_arrival"] = self.eta.value()
        if hasattr(self, "late"):
            data["late_checkout_until"] = self.late.value()
        if hasattr(self, "note"):
            data["note"] = self.note.toPlainText()
        return data

    def _save(self) -> None:
        data = self._payload()
        if self.mode == "walk_in":
            data["nights"] = self.nights.value()
            room = self.ctx.rooms.get(self._room_id) if self._room_id else None
            allow_dirty = False
            if room and room.hk_status in (HKStatus.DIRTY, HKStatus.CLEANING):
                if not confirm(self, "Room not ready", f"Room {room.number} is "
                               f"{HKStatus.LABELS[room.hk_status].lower()}. Check the guest in anyway?",
                               "Check in anyway"):
                    return
                allow_dirty = True
            payment = None
            if self.pay_amount.value() and self.ctx.can("billing.payment"):
                payment = {"amount": self.pay_amount.value(), "method_id": self.pay_method.currentData(),
                           "reference": self.pay_ref.text()}
            res_id = self.attempt(lambda: self.ctx.reservations.walk_in(data, allow_dirty=allow_dirty,
                                                                        payment=payment))
            if res_id:
                self.app.toast(f"Checked in to room {room.number if room else ''}")
        elif self.mode == "edit":
            if self.in_house:
                data.pop("room_id", None)
                data.pop("check_in_date", None)
                data.pop("guest_id", None)
                if self.rate.value() == f"{self.res.nightly_rate / 100:.2f}":
                    data.pop("nightly_rate")
            elif not self.ctx.can("reservations.override_rate"):
                data.pop("nightly_rate")
            if self.attempt(lambda: (self.ctx.reservations.update(self.res.id, data), self.res.id)[1]):
                self.app.toast("Reservation updated")
        else:
            if not self.ctx.can("reservations.override_rate"):
                data.pop("nightly_rate")
            res_id = self.attempt(lambda: self.ctx.reservations.create(data))
            if res_id:
                res = self.ctx.reservations.get(res_id)
                self.app.toast(f"Reservation {res.confirmation_no} created for {res.guest_name}")


__all__ = ["ReservationDialog", "Badge", "QFrame", "QLabel", "QWidget"]
