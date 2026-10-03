"""Guest folios: charges, taxes, discounts, payments, refunds and invoices."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from motelmg.core import validation as v
from motelmg.core.dates import iter_nights, parse_optional_date
from motelmg.core.enums import ChargeKind, PaymentKind, ReservationStatus
from motelmg.core.errors import ConflictError, NotFoundError, ValidationError
from motelmg.core.money import format_percent, parse_amount, parse_percent, percent_of
from motelmg.models import Folio, Payment, Quote, Reservation, Room, TaxSummary
from motelmg.services.pricing import compute_quote, discounted_amount, taxes_for

CLOSED = (ReservationStatus.CHECKED_OUT, ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW)


class BillingService:
    def __init__(self, ctx):
        self.ctx = ctx
        self._catalog: tuple[list, list] | None = None

    def invalidate_cache(self) -> None:
        """Called whenever taxes or charge items change."""
        self._catalog = None

    def _taxes_and_items(self) -> tuple[list, list]:
        if self._catalog is None:
            items = [i for i in self.repo.charge_items() if i.auto_apply != "none" and i.default_amount > 0]
            self._catalog = (self.repo.taxes(), items)
        return self._catalog

    @property
    def repo(self):
        return self.ctx.repo_folio

    def _reservation(self, res_id: int) -> Reservation:
        res = self.ctx.repo_res.get(res_id)
        if not res:
            raise NotFoundError("Reservation not found.")
        return res

    # -- folio -----------------------------------------------------------------------
    def folio(self, res_id: int) -> Folio:
        res = self._reservation(res_id)
        all_lines = self.repo.charges(res_id)
        charges = [c for c in all_lines if c.kind != ChargeKind.TAX]
        tax_lines = [c for c in all_lines if c.kind == ChargeKind.TAX]
        tax_totals: dict[str, int] = {}
        for line in tax_lines:
            if not line.is_void:
                tax_totals[line.description] = tax_totals.get(line.description, 0) + line.amount
        payments = self.repo.payments(res_id)
        subtotal = sum(c.amount for c in charges if not c.is_void)
        tax_total = sum(tax_totals.values())
        paid = sum(p.signed_amount for p in payments if not p.is_void)
        invoice = self.repo.invoice_for(res_id)
        from motelmg.core.dates import parse_datetime
        return Folio(
            reservation=res, charges=charges, tax_lines=tax_lines, payments=payments,
            taxes=[TaxSummary(name, amount) for name, amount in tax_totals.items() if amount],
            subtotal=subtotal, tax_total=tax_total, total=subtotal + tax_total, paid=paid,
            balance=subtotal + tax_total - paid,
            invoice_no=invoice["invoice_no"] if invoice else "",
            invoice_issued_at=parse_datetime(invoice["issued_at"]) if invoice else None)

    def balance(self, res_id: int) -> int:
        return self.repo.charges_total(res_id) - self.repo.paid_total(res_id)

    def auto_items(self):
        return list(self._taxes_and_items()[1])

    def quote(self, *, nights: int, nightly_rate: int, discount_bp: int = 0, discount_name: str = "") -> Quote:
        taxes, items = self._taxes_and_items()
        return compute_quote(nights=nights, nightly_rate=nightly_rate, discount_bp=discount_bp,
                             discount_name=discount_name, taxes=taxes, auto_items=items,
                             deposit_percent=self.ctx.settings.get_int("policy.deposit_percent"))

    def nights_value(self, nights: int, nightly_rate: int, discount_bp: int = 0) -> int:
        """Total (with taxes and per-night fees) of ``nights`` extra room nights."""
        taxes, items = self._taxes_and_items()
        per_night_items = [i for i in items if i.auto_apply == "per_night"]
        return compute_quote(nights=nights, nightly_rate=nightly_rate, discount_bp=discount_bp,
                             taxes=taxes, auto_items=per_night_items).total

    def estimate(self, res: Reservation) -> int:
        """Expected total of a stay: posted charges once in house, a quote before."""
        if res.status == ReservationStatus.CONFIRMED:
            return self.quote(nights=res.nights, nightly_rate=res.nightly_rate, discount_bp=res.discount_bp).total
        return res.total

    # -- posting engine (callers hold a transaction) -------------------------------
    def _post(self, res: Reservation, *, kind: str, description: str, unit_amount: int, quantity: int = 1,
              taxable: bool, service_date: date, scope: str, room_id: int | None = None,
              item_id: int | None = None, parent_id: int | None = None) -> int:
        now = self.ctx.now_str()
        amount = unit_amount * quantity
        charge_id = self.repo.insert_charge({
            "reservation_id": res.id, "kind": kind, "description": description,
            "service_date": service_date.isoformat(), "quantity": quantity, "unit_amount": unit_amount,
            "amount": amount, "taxable": int(taxable), "parent_id": parent_id, "room_id": room_id,
            "charge_item_id": item_id, "posted_by": self.ctx.user_id, "posted_at": now})
        if taxable:
            for portion in taxes_for(unit_amount, scope=scope, kind=kind, quantity=1, taxes=self.repo.taxes()):
                tax = portion.tax
                label = f"{tax.name} ({format_percent(tax.value)})" if tax.kind == "percent" else tax.name
                self.repo.insert_charge({
                    "reservation_id": res.id, "kind": ChargeKind.TAX, "description": label,
                    "service_date": service_date.isoformat(), "quantity": quantity,
                    "unit_amount": portion.amount, "amount": portion.amount * quantity, "taxable": 0,
                    "parent_id": charge_id, "tax_id": tax.id, "posted_by": self.ctx.user_id, "posted_at": now})
        return charge_id

    def _post_room_night(self, res: Reservation, night: date, room: Room) -> None:
        room_line = self._post(res, kind=ChargeKind.ROOM, description=f"Room {room.number} · {room.type_name}",
                               unit_amount=res.nightly_rate, taxable=True, service_date=night, scope="room",
                               room_id=room.id)
        if res.discount_bp:
            label = f"Discount{' - ' + res.discount_name if res.discount_name else ''} " \
                    f"({format_percent(res.discount_bp)})"
            self._post(res, kind=ChargeKind.DISCOUNT, description=label,
                       unit_amount=discounted_amount(res.nightly_rate, res.discount_bp), taxable=True,
                       service_date=night, scope="room", parent_id=room_line)
        for item in self.auto_items():
            if item.auto_apply == "per_night":
                self._post(res, kind=item.category, description=item.name, unit_amount=item.default_amount,
                           taxable=item.taxable, service_date=night, scope="extras", item_id=item.id,
                           parent_id=room_line)

    def _post_stay_fees(self, res: Reservation, day: date) -> None:
        for item in self.auto_items():
            if item.auto_apply == "per_stay":
                self._post(res, kind=item.category, description=item.name, unit_amount=item.default_amount,
                           taxable=item.taxable, service_date=day, scope="extras", item_id=item.id)

    def _void_tree(self, charge_id: int, reason: str) -> None:
        now = self.ctx.now_str()
        for child in self.repo.child_ids(charge_id):
            self._void_tree(child, reason)
        self.repo.void_charge(charge_id, reason, self.ctx.user_id, now)

    def _sync_room_nights(self, res_id: int, reason: str) -> None:
        """Make posted room nights match the reservation's dates exactly."""
        res = self._reservation(res_id)
        room = self.ctx.rooms.get(res.room_id)
        wanted = set(iter_nights(res.check_in_date, res.check_out_date))
        existing = self.repo.active_room_nights(res_id)
        for night, line in existing.items():
            if night not in wanted:
                self._void_tree(line.id, reason)
        for night in sorted(wanted):
            if night not in existing:
                self._post_room_night(res, night, room)

    def _void_nights_from(self, res_id: int, from_date: date, reason: str) -> None:
        for night, line in self.repo.active_room_nights(res_id).items():
            if night >= from_date:
                self._void_tree(line.id, reason)

    def _post_system_fee(self, res: Reservation, code: str, amount: int, description: str | None = None) -> int | None:
        if amount <= 0:
            return None
        item = self.repo.charge_item_by_code(code)
        if item is None:
            raise NotFoundError(f"Fee item {code} is missing from the catalog.")
        return self._post(res, kind=ChargeKind.FEE, description=description or item.name, unit_amount=amount,
                          taxable=item.taxable, service_date=self.ctx.clock.today(), scope="extras",
                          item_id=item.id)

    def fee_with_tax(self, code: str, amount: int) -> int:
        item = self.repo.charge_item_by_code(code)
        if item is None or amount <= 0:
            return max(amount, 0)
        if not item.taxable:
            return amount
        return amount + sum(p.amount for p in taxes_for(amount, scope="extras", kind="fee", quantity=1,
                                                         taxes=self.repo.taxes()))

    def room_nights_value_from(self, res_id: int, from_date: date) -> int:
        """Total (incl. children/taxes) of active room nights on/after ``from_date``."""
        total = 0
        lines = self.repo.charges(res_id, include_void=False)
        by_parent: dict[int | None, list] = {}
        for line in lines:
            by_parent.setdefault(line.parent_id, []).append(line)

        def tree(line) -> int:
            return line.amount + sum(tree(child) for child in by_parent.get(line.id, []))

        for line in lines:
            if line.kind == ChargeKind.ROOM and line.service_date >= from_date:
                total += tree(line)
        return total

    # -- public charge operations ----------------------------------------------------
    def post_charge(self, res_id: int, data: dict[str, Any]) -> int:
        self.ctx.require("billing.charge")
        res = self._reservation(res_id)
        if res.status == ReservationStatus.CONFIRMED:
            raise ConflictError("Charges can be posted once the guest is checked in. "
                                "To collect money in advance, record a deposit.")
        item = None
        if data.get("item_id"):
            item = self.repo.charge_item(int(data["item_id"]))
            if item is None:
                raise ValidationError("Select a valid charge.", field="item_id")
        description = v.required(data.get("description") or (item.name if item else ""), "Description",
                                 "description", max_len=120)
        amount = parse_amount(data.get("amount"), field="amount", label="Amount", allow_zero=False)
        quantity = v.int_range(data.get("quantity", 1), "Quantity", "quantity", 1, 100)
        taxable = bool(data.get("taxable", item.taxable if item else True))
        service_date = parse_optional_date(data.get("service_date"), field="service_date") or self.ctx.clock.today()
        if service_date > self.ctx.clock.today():
            raise ValidationError("Charges cannot be dated in the future.", field="service_date")
        if service_date < res.check_in_date - timedelta(days=1):
            raise ValidationError("Charge date is before the guest's arrival.", field="service_date")
        kind = item.category if item else (data.get("kind") or ChargeKind.EXTRA)
        if kind not in (ChargeKind.FEE, ChargeKind.EXTRA):
            kind = ChargeKind.EXTRA
        with self.ctx.db.transaction():
            charge_id = self._post(res, kind=kind, description=description, unit_amount=amount,
                                   quantity=quantity, taxable=taxable, service_date=service_date, scope="extras",
                                   item_id=item.id if item else None)
            self.ctx.audit.log("billing.charge", "reservation", res.id,
                               f"Posted {description} {self.ctx.settings.money(amount * quantity)} "
                               f"to {res.confirmation_no}", {"charge_id": charge_id, "quantity": quantity})
        self.ctx.events.emit("billing", "reservations")
        return charge_id

    def apply_discount(self, res_id: int, *, mode: str, value: Any, reason: str) -> int:
        self.ctx.require("billing.discount")
        res = self._reservation(res_id)
        if res.status not in (ReservationStatus.CHECKED_IN, ReservationStatus.CHECKED_OUT):
            raise ConflictError("Discounts can be applied to in-house or checked-out stays.")
        reason = v.required(reason, "Reason", "reason", max_len=200)
        room_total = sum(c.amount for c in self.repo.charges(res_id, include_void=False)
                         if c.kind in (ChargeKind.ROOM, ChargeKind.DISCOUNT))
        if mode == "percent":
            bp = parse_percent(value, field="value", label="Discount")
            amount = percent_of(room_total, bp)
            label = f"Discount ({format_percent(bp)}) - {reason}"
        elif mode == "amount":
            amount = parse_amount(value, field="value", label="Discount", allow_zero=False)
            label = f"Discount - {reason}"
        else:
            raise ValidationError("Choose percent or amount.", field="mode")
        if amount <= 0:
            raise ValidationError("The discount works out to zero.", field="value")
        if amount > room_total:
            raise ValidationError("The discount cannot exceed the room charges "
                                  f"({self.ctx.settings.money(room_total)}).", field="value")
        with self.ctx.db.transaction():
            charge_id = self._post(res, kind=ChargeKind.DISCOUNT, description=label, unit_amount=-amount,
                                   taxable=True, service_date=self.ctx.clock.today(), scope="room")
            self.ctx.audit.log("billing.discount", "reservation", res.id,
                               f"Applied discount {self.ctx.settings.money(amount)} to {res.confirmation_no}: "
                               f"{reason}")
        self.ctx.events.emit("billing", "reservations")
        return charge_id

    def post_adjustment(self, res_id: int, *, amount: Any, reason: str) -> int:
        """Non-taxable correction (positive or negative). Requires void permission."""
        self.ctx.require("billing.void")
        res = self._reservation(res_id)
        if res.status == ReservationStatus.CONFIRMED:
            raise ConflictError("Adjustments can be made after check-in.")
        reason = v.required(reason, "Reason", "reason", max_len=200)
        cents = parse_amount(amount, field="amount", allow_negative=True, allow_zero=False)
        with self.ctx.db.transaction():
            charge_id = self._post(res, kind=ChargeKind.ADJUSTMENT, description=f"Adjustment - {reason}",
                                   unit_amount=cents, taxable=False, service_date=self.ctx.clock.today(),
                                   scope="extras")
            self.ctx.audit.log("billing.adjustment", "reservation", res.id,
                               f"Adjustment {self.ctx.settings.money(cents)} on {res.confirmation_no}: {reason}")
        self.ctx.events.emit("billing", "reservations")
        return charge_id

    def void_charge(self, charge_id: int, reason: str) -> None:
        self.ctx.require("billing.void")
        charge = self.repo.get_charge(charge_id)
        if charge is None:
            raise NotFoundError("Charge not found.")
        if charge.is_void:
            raise ConflictError("This charge is already void.")
        if charge.kind == ChargeKind.ROOM:
            raise ConflictError("Room nights follow the stay dates. Change the departure date, or apply a "
                                "discount to comp a night.")
        if charge.kind == ChargeKind.TAX:
            raise ConflictError("Taxes are voided together with the charge they belong to.")
        reason = v.required(reason, "Reason", "reason", max_len=200)
        res = self._reservation(charge.reservation_id)
        with self.ctx.db.transaction():
            self._void_tree(charge_id, reason)
            self.ctx.audit.log("billing.void_charge", "reservation", res.id,
                               f"Voided '{charge.description}' {self.ctx.settings.money(charge.amount)} on "
                               f"{res.confirmation_no}: {reason}", {"charge_id": charge_id})
        self.ctx.events.emit("billing", "reservations")

    # -- payments ------------------------------------------------------------------------
    def _receipt_no(self) -> str:
        number = self.ctx.db.next_counter("receipt")
        return f"{self.ctx.settings.get_str('numbering.receipt_prefix')}{number:06d}"

    def record_payment(self, res_id: int, *, amount: Any, method_id: int, reference: str = "",
                       notes: str = "") -> int:
        self.ctx.require("billing.payment")
        res = self._reservation(res_id)
        cents = parse_amount(amount, field="amount", allow_zero=False)
        method = self.repo.payment_method(int(method_id)) if method_id else None
        if method is None or not method.is_active:
            raise ValidationError("Select a payment method.", field="method_id")
        reference = v.optional(reference, "Reference", "reference", max_len=60)
        if method.requires_reference and not reference:
            raise ValidationError(f"{method.name} payments need a reference (e.g. last 4 digits or check no.).",
                                  field="reference")
        notes = v.optional(notes, "Notes", "notes", max_len=300)
        kind = PaymentKind.DEPOSIT if res.status == ReservationStatus.CONFIRMED else PaymentKind.PAYMENT
        if res.status in CLOSED:
            balance = self.balance(res_id)
            if balance <= 0:
                raise ConflictError("This folio is fully paid.")
            if cents > balance:
                raise ValidationError(f"The balance due is only {self.ctx.settings.money(balance)}.", field="amount")
        with self.ctx.db.transaction():
            receipt = self._receipt_no()
            payment_id = self.repo.insert_payment({
                "reservation_id": res.id, "kind": kind, "method_id": method.id, "amount": cents,
                "reference": reference, "notes": notes, "receipt_no": receipt, "created_by": self.ctx.user_id,
                "created_at": self.ctx.now_str()})
            self.ctx.audit.log(f"billing.{kind}", "reservation", res.id,
                               f"{PaymentKind.LABELS[kind]} {self.ctx.settings.money(cents)} ({method.name}) "
                               f"on {res.confirmation_no}, receipt {receipt}", {"payment_id": payment_id})
        self.ctx.events.emit("billing", "reservations")
        return payment_id

    def refund(self, res_id: int, *, amount: Any, method_id: int, reason: str, reference: str = "") -> int:
        self.ctx.require("billing.refund")
        res = self._reservation(res_id)
        cents = parse_amount(amount, field="amount", allow_zero=False)
        method = self.repo.payment_method(int(method_id)) if method_id else None
        if method is None:
            raise ValidationError("Select how the refund is paid out.", field="method_id")
        reason = v.required(reason, "Reason", "reason", max_len=300)
        reference = v.optional(reference, "Reference", "reference", max_len=60)
        paid = self.repo.paid_total(res_id)
        if cents > paid:
            raise ValidationError(f"You can refund at most {self.ctx.settings.money(paid)} "
                                  "(the amount paid on this folio).", field="amount")
        with self.ctx.db.transaction():
            receipt = self._receipt_no()
            payment_id = self.repo.insert_payment({
                "reservation_id": res.id, "kind": PaymentKind.REFUND, "method_id": method.id, "amount": cents,
                "reference": reference, "notes": reason, "receipt_no": receipt, "created_by": self.ctx.user_id,
                "created_at": self.ctx.now_str()})
            self.ctx.audit.log("billing.refund", "reservation", res.id,
                               f"Refunded {self.ctx.settings.money(cents)} ({method.name}) on "
                               f"{res.confirmation_no}: {reason}", {"payment_id": payment_id})
        self.ctx.events.emit("billing", "reservations")
        return payment_id

    def void_payment(self, payment_id: int, reason: str) -> None:
        self.ctx.require("billing.void")
        payment = self.repo.get_payment(payment_id)
        if payment is None:
            raise NotFoundError("Payment not found.")
        if payment.is_void:
            raise ConflictError("This payment is already void.")
        reason = v.required(reason, "Reason", "reason", max_len=200)
        if payment.kind != PaymentKind.REFUND:
            paid_after = self.repo.paid_total(payment.reservation_id) - payment.amount
            if paid_after < 0:
                raise ConflictError("Void the refund issued against this payment first.")
        with self.ctx.db.transaction():
            self.repo.void_payment(payment_id, reason, self.ctx.user_id, self.ctx.now_str())
            self.ctx.audit.log("billing.void_payment", "reservation", payment.reservation_id,
                               f"Voided {PaymentKind.LABELS[payment.kind].lower()} {payment.receipt_no} "
                               f"{self.ctx.settings.money(payment.amount)}: {reason}", {"payment_id": payment_id})
        self.ctx.events.emit("billing", "reservations")

    def get_payment(self, payment_id: int) -> Payment:
        payment = self.repo.get_payment(payment_id)
        if payment is None:
            raise NotFoundError("Payment not found.")
        return payment

    # -- invoices & lists -----------------------------------------------------------------
    def issue_invoice(self, res_id: int) -> str:
        existing = self.repo.invoice_for(res_id)
        if existing:
            return existing["invoice_no"]
        folio = self.folio(res_id)
        with self.ctx.db.transaction():
            number = self.ctx.db.next_counter("invoice")
            invoice_no = f"{self.ctx.settings.get_str('numbering.invoice_prefix')}{number:06d}"
            self.repo.insert_invoice({"invoice_no": invoice_no, "reservation_id": res_id,
                                      "issued_at": self.ctx.now_str(), "issued_by": self.ctx.user_id,
                                      "total": folio.total, "paid": folio.paid, "balance": folio.balance})
            self.ctx.audit.log("billing.invoice", "reservation", res_id,
                               f"Issued invoice {invoice_no} for {folio.reservation.confirmation_no}")
        return invoice_no

    def transactions(self, **filters) -> list[Payment]:
        self.ctx.require("billing.view")
        return self.repo.search_payments(**filters)

    def outstanding(self, min_balance: int = 1):
        self.ctx.require("billing.view")
        return self.repo.balances(min_balance)

    def credits(self):
        return self.repo.credits()

    def invoices(self, **filters):
        self.ctx.require("billing.view")
        return self.repo.list_invoices(**filters)
