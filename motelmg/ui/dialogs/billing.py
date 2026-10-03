"""Payments, refunds, charges, discounts and adjustments."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QRadioButton

from motelmg.core.enums import ReservationStatus
from motelmg.ui.widgets.common import Card, KeyValueGrid, label
from motelmg.ui.widgets.dialogs import BaseDialog
from motelmg.ui.widgets.forms import DateEdit, FormGrid, MoneyEdit, combo, line, on_change, spin, text_area


def folio_summary(app, res_id: int) -> tuple[Card, int]:
    folio = app.ctx.billing.folio(res_id)
    res = folio.reservation
    card = Card(padding=14, spacing=6)
    grid = KeyValueGrid(columns=2)
    grid.add("guest", "Guest", res.guest_name)
    grid.add("res", "Reservation", f"{res.confirmation_no} · Room {res.room_number}")
    if res.status == ReservationStatus.CONFIRMED:
        estimate = app.ctx.billing.estimate(res)
        grid.add("total", "Estimated stay", app.fmt.money(estimate))
        grid.add("paid", "Deposits", app.fmt.money(folio.paid))
    else:
        grid.add("total", "Charges", app.fmt.money(folio.total))
        grid.add("paid", "Paid", app.fmt.money(folio.paid))
    balance = folio.balance
    grid.add("balance", "Balance due" if balance >= 0 else "Credit", app.fmt.money(abs(balance)))
    card.body.addWidget(grid)
    return card, balance


class PaymentDialog(BaseDialog):
    def __init__(self, parent, app, res_id: int, *, refund: bool = False, amount: int | None = None):
        self.app, self.ctx, self.res_id, self.refund = app, app.ctx, res_id, refund
        res = self.ctx.reservations.get(res_id)
        is_deposit = res.status == ReservationStatus.CONFIRMED and not refund
        title = "Issue refund" if refund else ("Record deposit" if is_deposit else "Take payment")
        super().__init__(parent, title, f"{res.confirmation_no} · {res.guest_name}",
                         icon_name="undo" if refund else "dollar", tone="red" if refund else "green", width=520)
        self.result_value = None
        summary, balance = folio_summary(app, res_id)
        self.body.addWidget(summary)
        self.form = self.register_form(FormGrid(2))
        self.amount = MoneyEdit()
        if amount is not None:
            self.amount.set_cents(amount)
        elif refund and balance < 0:
            self.amount.set_cents(-balance)
        elif not refund and balance > 0:
            self.amount.set_cents(balance)
        elif is_deposit:
            quote = self.ctx.billing.estimate(res)
            deposit_pct = self.ctx.settings.get_int("policy.deposit_percent")
            self.amount.set_cents(quote * deposit_pct // 100 if deposit_pct else res.nightly_rate)
        self.methods = self.ctx.catalog.payment_methods()
        self.method = combo([(m.name, m.id) for m in self.methods])
        self.form.add("amount", "Refund amount" if refund else "Amount", self.amount, required=True)
        self.form.add("method_id", "Refund to" if refund else "Payment method", self.method, required=True)
        self.reference = line(placeholder="Card last 4, check no., transaction ID", max_len=60)
        self.form.add("reference", "Reference", self.reference, span=2)
        self.tendered = MoneyEdit()
        self.change = label("", "h3")
        if not refund:
            self.form.add("tendered", "Cash received", self.tendered, hint="Optional: calculates change due")
            self.form.add("change", "Change due", self.change)
        self.notes = text_area("", "Why is this refund being issued?" if refund else "Optional note", 54)
        self.form.add("reason" if refund else "notes", "Reason" if refund else "Notes", self.notes, span=2,
                      required=refund)
        self.body.addWidget(self.form)
        self.print_receipt = QCheckBox("Print a receipt")
        self.body.addWidget(self.print_receipt)
        on_change(self.method, self._method_changed)
        on_change(self.tendered, self._update_change)
        on_change(self.amount, self._update_change)
        self._method_changed()
        self.add_cancel()
        self.add_footer_button(title, self._save, "danger" if refund else "primary",
                               icon_name="check", default=True)
        self.amount.setFocus()
        self.amount.selectAll()

    def _method(self):
        return next((m for m in self.methods if m.id == self.method.currentData()), None)

    def _method_changed(self) -> None:
        method = self._method()
        cash = bool(method and method.is_cash)
        if "tendered" in self.form.fields:
            self.form.set_visible("tendered", cash and not self.refund)
            self.form.set_visible("change", cash and not self.refund)
        self.form.labels["reference"].setText("Reference *" if method and method.requires_reference else "Reference")
        self._update_change()

    def _update_change(self) -> None:
        if self.refund:
            return
        tendered = self.tendered.cents()
        due = self.amount.cents()
        self.change.setText(self.app.fmt.money(tendered - due) if tendered >= due and tendered else "—")

    def _save(self) -> None:
        billing = self.ctx.billing
        if self.refund:
            payment_id = self.attempt(lambda: billing.refund(
                self.res_id, amount=self.amount.value(), method_id=self.method.currentData(),
                reason=self.notes.toPlainText(), reference=self.reference.text()), accept=False)
        else:
            payment_id = self.attempt(lambda: billing.record_payment(
                self.res_id, amount=self.amount.value(), method_id=self.method.currentData(),
                reference=self.reference.text(), notes=self.notes.toPlainText()), accept=False)
        if not payment_id:
            return
        payment = billing.get_payment(payment_id)
        self.app.toast(f"{'Refund' if self.refund else 'Payment'} of {self.app.fmt.money(payment.amount)} recorded "
                       f"(receipt {payment.receipt_no})")
        self.result_value = payment_id
        self.accept()
        if self.print_receipt.isChecked():
            self.app.actions.print_payment(payment_id, parent=self.parent())


class ChargeDialog(BaseDialog):
    def __init__(self, parent, app, res_id: int):
        self.app, self.ctx, self.res_id = app, app.ctx, res_id
        res = self.ctx.reservations.get(res_id)
        super().__init__(parent, "Add charge", f"{res.confirmation_no} · {res.guest_name} · "
                         f"Room {res.room_number}", icon_name="plus", width=520)
        self.items = self.ctx.catalog.charge_items()
        self.form = self.register_form(FormGrid(2))
        options = [("Custom charge…", None)] + [(f"{i.name}  ({app.fmt.money(i.default_amount)})"
                                                      if i.default_amount else i.name, i.id) for i in self.items]
        self.item = combo(options)
        self.description = line(max_len=120)
        self.amount = MoneyEdit()
        self.quantity = spin(1, 1, 100)
        self.taxable = QCheckBox("Taxable")
        self.taxable.setChecked(True)
        today = self.ctx.clock.today()
        self.date = DateEdit(today)
        self.date.setMaximumDate(self.date.date())
        self.form.add("item_id", "Charge", self.item, span=2)
        self.form.add("description", "Description", self.description, required=True, span=2)
        self.form.add("amount", "Unit price", self.amount, required=True)
        self.form.add("quantity", "Quantity", self.quantity)
        self.form.add("service_date", "Date", self.date)
        self.form.add("taxable", "", self.taxable)
        self.total = label("", "h3")
        self.body.addWidget(self.form)
        row = QHBoxLayout()
        row.addWidget(label("Total before tax", "muted"))
        row.addStretch(1)
        row.addWidget(self.total)
        self.body.addLayout(row)
        on_change(self.item, self._item_changed)
        on_change(self.amount, self._update_total)
        on_change(self.quantity, self._update_total)
        self.add_cancel()
        self.add_footer_button("Post charge", self._save, "primary", icon_name="check", default=True)
        self._update_total()

    def _item_changed(self) -> None:
        item = next((i for i in self.items if i.id == self.item.currentData()), None)
        if item:
            self.description.setText(item.name)
            if item.default_amount:
                self.amount.set_cents(item.default_amount)
            self.taxable.setChecked(item.taxable)
        self._update_total()

    def _update_total(self) -> None:
        self.total.setText(self.app.fmt.money(self.amount.cents() * self.quantity.value()))

    def _save(self) -> None:
        data = self.form.values()
        if self.attempt(lambda: self.ctx.billing.post_charge(self.res_id, data)):
            self.app.toast(f"Posted {data['description']}")


class DiscountDialog(BaseDialog):
    def __init__(self, parent, app, res_id: int):
        self.app, self.ctx, self.res_id = app, app.ctx, res_id
        res = self.ctx.reservations.get(res_id)
        super().__init__(parent, "Apply discount", f"{res.confirmation_no} · {res.guest_name}",
                         icon_name="percent", tone="purple", width=460)
        self.body.addWidget(label("Discounts reduce the room charges (and the taxes on them).", "muted", wrap=True))
        modes = QHBoxLayout()
        self.pct = QRadioButton("Percentage of room charges")
        self.amt = QRadioButton("Fixed amount")
        self.pct.setChecked(True)
        modes.addWidget(self.pct)
        modes.addWidget(self.amt)
        modes.addStretch(1)
        self.body.addLayout(modes)
        self.form = self.register_form(FormGrid(1))
        self.value = MoneyEdit(placeholder="10")
        self.reason = line(placeholder="e.g. Noise complaint, loyalty, service recovery", max_len=200)
        self.form.add("value", "Discount", self.value, required=True)
        self.form.add("reason", "Reason", self.reason, required=True)
        self.body.addWidget(self.form)
        self.add_cancel()
        self.add_footer_button("Apply discount", self._save, "primary", default=True)

    def _save(self) -> None:
        mode = "percent" if self.pct.isChecked() else "amount"
        if self.attempt(lambda: self.ctx.billing.apply_discount(self.res_id, mode=mode, value=self.value.value(),
                                                                reason=self.reason.text())):
            self.app.toast("Discount applied")


class AdjustmentDialog(BaseDialog):
    def __init__(self, parent, app, res_id: int):
        self.app, self.ctx, self.res_id = app, app.ctx, res_id
        super().__init__(parent, "Folio adjustment", "Correct the folio with a non-taxable credit (negative) or "
                         "debit (positive) amount.", icon_name="edit", width=460)
        self.form = self.register_form(FormGrid(1))
        self.amount = MoneyEdit(allow_negative=True, placeholder="-25.00")
        self.reason = line(max_len=200)
        self.form.add("amount", "Amount", self.amount, required=True)
        self.form.add("reason", "Reason", self.reason, required=True)
        self.body.addWidget(self.form)
        self.add_cancel()
        self.add_footer_button("Post adjustment", self._save, "primary", default=True)

    def _save(self) -> None:
        if self.attempt(lambda: self.ctx.billing.post_adjustment(self.res_id, amount=self.amount.value(),
                                                                 reason=self.reason.text())):
            self.app.toast("Adjustment posted")
