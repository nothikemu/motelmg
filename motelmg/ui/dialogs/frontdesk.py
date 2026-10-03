"""Check-in, check-out, room transfer, cancellation and no-show dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QRadioButton, QVBoxLayout

from motelmg.core.enums import HKStatus, IdType, ReservationStatus
from motelmg.ui.widgets.common import clear_layout, Banner, Card, Divider, KeyValueGrid, label
from motelmg.ui.widgets.dialogs import BaseDialog, confirm
from motelmg.ui.widgets.forms import FormGrid, MoneyEdit, combo, line, on_change, text_area
from motelmg.ui.widgets.table import Column, DataTable


def _stay_card(app, res) -> Card:
    card = Card(padding=14, spacing=6)
    grid = KeyValueGrid(columns=2)
    fmt = app.fmt
    grid.add("guest", "Guest", res.guest_name)
    grid.add("conf", "Reservation", res.confirmation_no)
    grid.add("room", "Room", f"{res.room_number} · {res.room_type_name}")
    grid.add("guests", "Guests", f"{res.adults} adult(s)" + (f", {res.children} child(ren)" if res.children else ""))
    grid.add("arrive", "Arrival", fmt.date(res.check_in_date))
    grid.add("depart", "Departure", fmt.date(res.check_out_date))
    grid.add("nights", "Nights", str(res.nights))
    grid.add("rate", "Rate", fmt.money(res.nightly_rate) + (f" − {res.discount_name}" if res.discount_name else ""))
    card.body.addWidget(grid)
    if res.special_requests:
        card.body.addWidget(label(f"Requests: {res.special_requests}", "muted", wrap=True))
    return card


def _payment_form(app, amount: int) -> tuple[FormGrid, MoneyEdit, object, object]:
    form = FormGrid(3)
    money = MoneyEdit()
    if amount > 0:
        money.set_cents(amount)
    method = combo([(m.name, m.id) for m in app.ctx.catalog.payment_methods()])
    ref = line(placeholder="Last 4 / reference", max_len=60)
    form.add("amount", "Amount", money)
    form.add("method_id", "Method", method)
    form.add("reference", "Reference", ref)
    return form, money, method, ref


class CheckInDialog(BaseDialog):
    def __init__(self, parent, app, res_id: int):
        self.app, self.ctx, self.res_id = app, app.ctx, res_id
        self.preview = p = self.ctx.reservations.check_in_preview(res_id)
        res = p.reservation
        super().__init__(parent, f"Check in {res.guest_name}", f"{res.confirmation_no} · Room {res.room_number}",
                         icon_name="log-in", tone="green", width=700, scroll=True)
        self.resize(720, 760)
        self.body.addWidget(_stay_card(app, res))
        for warning in p.warnings:
            self.body.addWidget(Banner(warning, "warning"))
        for note in self.ctx.notes.important_for_guest(res.guest_id):
            self.body.addWidget(Banner(f"Guest note: {note.body}", "info"))
        self.allow_dirty = QCheckBox()
        if p.room_issue in ("out_of_service", "occupied", "inactive"):
            msg = {"out_of_service": f"Room {p.room.number} is out of service ({p.room.service_reason}).",
                   "occupied": f"Room {p.room.number} is still occupied by {p.occupied_by.guest_name if p.occupied_by else ''}.",
                   "inactive": f"Room {p.room.number} is archived."}[p.room_issue]
            self.body.addWidget(Banner(msg + " Move the reservation to another room first.", "error"))
        elif p.room_issue:
            text = {"dirty": "has not been cleaned yet", "cleaning": "is being cleaned right now",
                    "not_inspected": "has been cleaned but not inspected"}[p.room_issue]
            self.body.addWidget(Banner(f"Room {p.room.number} {text}.", "warning"))
            self.allow_dirty.setText("Check the guest in anyway (they will wait or accept the room as is)")
            self.body.addWidget(self.allow_dirty)

        # Early check-in fee
        self.early_fee = MoneyEdit(p.early_fee_default)
        self.early_check = QCheckBox("Charge early check-in fee")
        if p.early_hours:
            box = Card("Early check-in", padding=14)
            box.body.addWidget(label(f"Standard check-in time is {app.fmt.time(self.ctx.settings.check_in_time())}.",
                                     "muted"))
            row = QHBoxLayout()
            row.addWidget(self.early_check)
            row.addStretch(1)
            row.addWidget(self.early_fee)
            box.body.addLayout(row)
            self.body.addWidget(box)

        # Identification
        guest = p.guest
        id_card = Card("Identification", padding=14)
        self.id_form = self.register_form(FormGrid(3))
        self.id_type = combo([(v, k) for k, v in IdType.LABELS.items()], guest.id_type or "drivers_license")
        self.id_number = line(guest.id_number, max_len=40)
        self.plate = line(guest.vehicle_plate, "Optional", max_len=20)
        self.id_form.add("id_type", "ID type", self.id_type)
        self.id_form.add("id_number", "ID number", self.id_number, required=p.id_required)
        self.id_form.add("vehicle_plate", "Vehicle plate", self.plate)
        id_card.body.addWidget(self.id_form)
        if p.missing_id and p.id_required:
            id_card.body.addWidget(label("Policy requires an ID document before check-in.", "faint"))
        self.body.addWidget(id_card)

        # Payment
        pay = Card("Payment", padding=14)
        quote_total = p.quote.total if p.quote else 0
        due = max(quote_total - p.deposits, 0)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        for i, (k, v) in enumerate((("Stay total", app.fmt.money(quote_total)),
                                    ("Deposits paid", app.fmt.money(p.deposits)),
                                    ("Due at check-in", app.fmt.money(due)))):
            grid.addWidget(label(k, "overline"), 0, i)
            grid.addWidget(label(v, "kpi_small"), 1, i)
        pay.body.addLayout(grid)
        self.pay_form, self.pay_amount, self.pay_method, self.pay_ref = _payment_form(app, due)
        self.register_form(self.pay_form)
        pay.body.addWidget(self.pay_form)
        pay.body.addWidget(label("Leave the amount empty to collect payment at check-out.", "faint"))
        pay.setEnabled(self.ctx.can("billing.payment"))
        self.body.addWidget(pay)
        self.print_card = QCheckBox("Print registration card")
        self.print_card.setChecked(self.ctx.settings.get_bool("invoice.print_registration_card"))
        self.body.addWidget(self.print_card)

        self.add_cancel()
        self.ok = self.add_footer_button("Check in", self._save, "primary", icon_name="log-in", default=True)
        if p.blocking:
            self.ok.setEnabled(False)
            if self.ctx.can("reservations.transfer"):
                self.add_footer_button("Change room", self._change_room, "soft", icon_name="transfer", left=True)

    def _change_room(self) -> None:
        self.reject()
        self.app.actions.transfer(self.res_id)

    def _save(self) -> None:
        p = self.preview
        if p.room_issue in ("dirty", "cleaning", "not_inspected") and not self.allow_dirty.isChecked():
            self.banner.set("The room is not ready. Tick the box to check in anyway, or change the room.", "error")
            return
        guest = p.guest
        id_number = self.id_number.text().strip()
        plate = self.plate.text().strip()

        def run():
            with self.ctx.db.transaction():
                if id_number != guest.id_number or self.id_type.currentData() != guest.id_type or \
                        plate.upper() != guest.vehicle_plate:
                    self.ctx.guests.update_identity(guest.id, self.id_type.currentData() if id_number else "",
                                                    id_number, plate)
                payment = None
                if self.pay_amount.value() and self.ctx.can("billing.payment"):
                    payment = {"amount": self.pay_amount.value(), "method_id": self.pay_method.currentData(),
                               "reference": self.pay_ref.text()}
                early = self.early_fee.value() if self.early_check.isChecked() else None
                self.ctx.reservations.check_in(self.res_id, allow_dirty=self.allow_dirty.isChecked(),
                                               early_fee=early, payment=payment)
            return True

        if self.attempt(run):
            self.app.toast(f"{p.guest.full_name} checked in to room {p.room.number}")
            if self.print_card.isChecked():
                self.app.actions.print_registration(self.res_id)


class CheckOutDialog(BaseDialog):
    def __init__(self, parent, app, res_id: int):
        self.app, self.ctx, self.res_id = app, app.ctx, res_id
        self.preview = p = self.ctx.reservations.check_out_preview(res_id)
        res = p.reservation
        fmt = app.fmt
        super().__init__(parent, f"Check out {res.guest_name}", f"{res.confirmation_no} · Room {res.room_number}",
                         icon_name="log-out", tone="indigo", width=640, scroll=True)
        self.resize(660, 700)
        self.body.addWidget(_stay_card(app, res))
        self.extra_check = QCheckBox()
        self.late_check = QCheckBox("Charge late check-out fee")
        self.late_fee = MoneyEdit(p.late_fee_default)
        self.early_check = QCheckBox("Charge early departure fee")
        early_item = self.ctx.catalog.system_item("EARLY_DEPARTURE")
        self.early_fee = MoneyEdit(early_item.default_amount if early_item else 0)
        if p.early_departure:
            box = Card("Early departure", padding=14)
            box.body.addWidget(label(f"The guest is leaving {p.nights_removed} night(s) early. Unused nights worth "
                                     f"{fmt.money(p.removed_value)} will be removed from the folio.", wrap=True))
            row = QHBoxLayout()
            row.addWidget(self.early_check)
            row.addStretch(1)
            row.addWidget(self.early_fee)
            box.body.addLayout(row)
            self.body.addWidget(box)
        if p.extra_nights:
            box = Card("Stayed past departure date", padding=14)
            self.extra_check.setText(f"Post {p.extra_nights} extra night(s) ({fmt.money(p.extra_value)})")
            self.extra_check.setChecked(True)
            box.body.addWidget(self.extra_check)
            self.body.addWidget(box)
        if p.late:
            box = Card("Late check-out", padding=14)
            box.body.addWidget(label(f"Check-out time was {fmt.time(self.ctx.settings.check_out_time())}.", "muted"))
            row = QHBoxLayout()
            row.addWidget(self.late_check)
            row.addStretch(1)
            row.addWidget(self.late_fee)
            box.body.addLayout(row)
            self.body.addWidget(box)

        totals = Card("Folio", padding=14, spacing=6)
        self.totals_grid = QGridLayout()
        self.totals_grid.setHorizontalSpacing(12)
        totals.body.addLayout(self.totals_grid)
        self.body.addWidget(totals)
        self.balance_label = label("", "money_big")

        self.pay_card = Card("Settle balance", padding=14)
        self.pay_form, self.pay_amount, self.pay_method, self.pay_ref = _payment_form(app, 0)
        self.register_form(self.pay_form)
        self.pay_card.body.addWidget(self.pay_form)
        self.pay_card.setEnabled(self.ctx.can("billing.payment"))
        self.body.addWidget(self.pay_card)
        self.credit_banner = Banner("", "info")
        self.body.addWidget(self.credit_banner)
        self.allow_balance = QCheckBox("Check out with an open balance (direct bill / collect later)")
        self.allow_balance.setVisible(self.ctx.can("billing.checkout_balance"))
        self.body.addWidget(self.allow_balance)
        self.print_invoice = QCheckBox("Show the invoice for printing after check-out")
        self.print_invoice.setChecked(True)
        self.body.addWidget(self.print_invoice)
        self.body.addWidget(label(f"Room {res.room_number} will be marked dirty and a cleaning task created.",
                                  "faint"))
        for w in (self.extra_check, self.late_check, self.early_check, self.late_fee, self.early_fee):
            on_change(w, self._recalc)
        self.add_cancel()
        self.add_footer_button("Check out", self._save, "primary", icon_name="log-out", default=True)
        self._recalc()

    def _recalc(self) -> None:
        p, fmt = self.preview, self.app.fmt
        balance = p.folio.balance
        if p.early_departure:
            balance -= p.removed_value
            if self.early_check.isChecked():
                balance += self.ctx.billing.fee_with_tax("EARLY_DEPARTURE", self.early_fee.cents())
        if p.extra_nights and self.extra_check.isChecked():
            balance += p.extra_value
        if p.late and self.late_check.isChecked():
            balance += self.ctx.billing.fee_with_tax("LATE_CHECKOUT", self.late_fee.cents())
        self.estimated = balance
        clear_layout(self.totals_grid)
        values = (("Charges so far", fmt.money(p.folio.total)), ("Paid", fmt.money(p.folio.paid)),
                  ("Balance after check-out" if balance >= 0 else "Credit after check-out", fmt.money(abs(balance))))
        for i, (k, v) in enumerate(values):
            self.totals_grid.addWidget(label(k, "overline"), 0, i)
            self.totals_grid.addWidget(label(v, "kpi_small"), 1, i)
        self.pay_amount.set_cents(max(balance, 0) or None)
        self.pay_card.setVisible(balance > 0)
        self.allow_balance.setVisible(balance > 0 and self.ctx.can("billing.checkout_balance"))
        if balance < 0:
            self.credit_banner.set(f"The guest has a credit of {fmt.money(-balance)}. After check-out you will be "
                                   "offered to issue a refund.", "info")
        else:
            self.credit_banner.hide()

    def _save(self) -> None:
        p = self.preview
        payment = None
        if self.pay_card.isVisible() and self.pay_amount.value() and self.ctx.can("billing.payment"):
            payment = {"amount": self.pay_amount.value(), "method_id": self.pay_method.currentData(),
                       "reference": self.pay_ref.text()}
        late = self.late_fee.value() if (p.late and self.late_check.isChecked()) else None
        early = self.early_fee.value() if (p.early_departure and self.early_check.isChecked()) else None
        invoice = self.attempt(lambda: self.ctx.reservations.check_out(
            self.res_id, late_fee=late, early_departure_fee=early,
            post_extra_nights=self.extra_check.isChecked() if p.extra_nights else True,
            allow_balance=self.allow_balance.isChecked(), payment=payment))
        if not invoice:
            return
        self.app.toast(f"{p.reservation.guest_name} checked out — invoice {invoice}")
        balance = self.ctx.billing.balance(self.res_id)
        if balance < 0 and self.ctx.can("billing.refund"):
            if confirm(self.parent(), "Refund credit", f"The guest has a credit of {self.app.fmt.money(-balance)}. "
                       "Issue a refund now?", "Issue refund"):
                self.app.actions.take_payment(self.res_id, refund=True)
        if self.print_invoice.isChecked():
            self.app.actions.print_folio(self.res_id)


class TransferDialog(BaseDialog):
    def __init__(self, parent, app, res_id: int):
        self.app, self.ctx, self.res_id = app, app.ctx, res_id
        res = self.res = self.ctx.reservations.get(res_id)
        in_house = res.status == ReservationStatus.CHECKED_IN
        super().__init__(parent, "Move to another room" if in_house else "Change room",
                         f"{res.guest_name} · currently room {res.room_number} ({res.room_type_name})",
                         icon_name="transfer", width=700)
        today = self.ctx.clock.today()
        start = max(today, res.check_in_date)
        rooms = self.ctx.rooms.available_rooms(start, res.check_out_date, exclude_reservation=res.id,
                                               guests=res.guests_count)
        rooms = [r for r in rooms if r.id != res.room_id]
        occupied = self.ctx.repo_rooms.occupied_room_ids() if in_house else set()
        rows = []
        for r in rooms:
            if r.id in occupied:
                continue
            ready = r.hk_status in (HKStatus.CLEAN, HKStatus.INSPECTED)
            rows.append({"id": r.id, "number": r.number, "type": r.type_name, "beds": r.effective_beds,
                         "rate": r.effective_rate, "hk": HKStatus.LABELS[r.hk_status] if in_house else "Available",
                         "tone": "green" if ready or not in_house else "amber", "dirty": in_house and not ready})
        self.table = DataTable([
            Column("number", "Room", width=70, bold=True), Column("type", "Type", stretch=True),
            Column("beds", "Beds", width=130), Column("rate", "Rate", "money", width=90),
            Column("hk", "Status", "badge", width=110, tone=lambda r: r["tone"]),
        ], app.fmt, empty_icon="bed", empty_title="No other rooms are free",
            empty_text="No room is available for the rest of this stay.", row_height=34)
        self.table.set_rows(rows)
        self.table.setMinimumHeight(220)
        self.body.addWidget(label(f"Rooms free from {app.fmt.date(start)} to {app.fmt.date(res.check_out_date)}:",
                                  "muted"))
        self.body.addWidget(self.table, 1)
        self.form = self.register_form(FormGrid(1))
        self.reason = line(placeholder="e.g. AC not working, guest request, upgrade", max_len=200)
        self.form.add("reason", "Reason", self.reason, required=True)
        self.body.addWidget(self.form)
        rate_row = QVBoxLayout()
        self.keep_rate = QRadioButton(f"Keep the current rate ({app.fmt.money(res.nightly_rate)}/night)")
        self.new_rate = QRadioButton("Use the new room's standard rate")
        self.keep_rate.setChecked(True)
        rate_row.addWidget(self.keep_rate)
        rate_row.addWidget(self.new_rate)
        self.body.addLayout(rate_row)
        if in_house:
            self.body.addWidget(label(f"Nights from today are re-posted to the new room; room {res.room_number} will "
                                      "be marked dirty for housekeeping.", "faint", wrap=True))
        self.add_cancel()
        self.add_footer_button("Move guest" if in_house else "Change room", self._save, "primary",
                               icon_name="transfer", default=True)

    def _save(self) -> None:
        row = self.table.selected_row()
        if not row:
            self.banner.set("Select the new room.", "error")
            return
        allow_dirty = False
        if row.get("dirty"):
            if not confirm(self, "Room not ready", f"Room {row['number']} is not clean yet. Move the guest anyway?",
                           "Move anyway"):
                return
            allow_dirty = True
        if self.attempt(lambda: self.ctx.reservations.transfer(self.res_id, row["id"], self.reason.text(),
                                                               use_new_rate=self.new_rate.isChecked(),
                                                               allow_dirty=allow_dirty)):
            self.app.toast(f"{self.res.guest_name} moved to room {row['number']}")


class CancelDialog(BaseDialog):
    def __init__(self, parent, app, res_id: int, *, no_show: bool = False):
        self.app, self.ctx, self.res_id, self.no_show = app, app.ctx, res_id, no_show
        res = self.res = self.ctx.reservations.get(res_id)
        super().__init__(parent, "Mark as no-show" if no_show else "Cancel reservation",
                         f"{res.confirmation_no} · {res.guest_name} · {app.fmt.date(res.check_in_date)}",
                         icon_name="slash", tone="red", width=520)
        paid = self.ctx.repo_folio.paid_total(res_id)
        info = ("The room will be released for other guests." +
                (f" {app.fmt.money(paid)} has been paid as a deposit." if paid else ""))
        self.body.addWidget(label(info, "muted", wrap=True))
        self.form = self.register_form(FormGrid(2))
        item = self.ctx.catalog.system_item("NO_SHOW" if no_show else "CANCELLATION")
        self.fee = MoneyEdit(item.default_amount if item and item.default_amount else None, placeholder="0.00")
        if not no_show:
            self.reason = text_area("", "Why is the guest cancelling?", 60)
            self.form.add("reason", "Reason", self.reason, required=True, span=2)
        self.form.add("fee", "No-show fee" if no_show else "Cancellation fee", self.fee,
                      hint="Leave empty for no fee")
        first_night = label(f"First night: {app.fmt.money(res.nightly_rate)}", "faint")
        self.form.add("first", "", first_night)
        self.body.addWidget(self.form)
        btn_row = QHBoxLayout()
        from motelmg.ui.widgets.common import button
        btn_row.addWidget(button("Charge first night", variant="link",
                                 on_click=lambda: self.fee.set_cents(res.nightly_rate)))
        btn_row.addStretch(1)
        self.body.addLayout(btn_row)
        self.body.addWidget(Divider())
        self.refund_credit = QCheckBox("Refund any remaining deposit afterwards")
        self.refund_credit.setChecked(paid > 0)
        self.refund_credit.setVisible(paid > 0 and self.ctx.can("billing.refund"))
        self.body.addWidget(self.refund_credit)
        self.add_footer_button("Keep reservation", self.reject)
        self.add_footer_button("Mark no-show" if no_show else "Cancel reservation", self._save, "danger",
                               default=True)

    def _save(self) -> None:
        fee = self.fee.value() or None
        if self.no_show:
            balance = self.attempt(lambda: self.ctx.reservations.mark_no_show(self.res_id, fee=fee))
        else:
            balance = self.attempt(lambda: self.ctx.reservations.cancel(self.res_id, self.reason.toPlainText(),
                                                                       fee=fee))
        if balance is None:
            return
        self.app.toast(f"{self.res.confirmation_no} {'marked as no-show' if self.no_show else 'cancelled'}")
        balance = self.ctx.billing.balance(self.res_id)
        if balance < 0 and self.refund_credit.isChecked():
            self.app.actions.take_payment(self.res_id, refund=True)
