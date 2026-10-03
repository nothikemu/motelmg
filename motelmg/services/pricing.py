"""Pure pricing calculations shared by quotes and folio posting.

Keeping these as side-effect free functions guarantees that the estimate a
guest is quoted at booking time is computed exactly the same way as the
charges that are later posted to their folio.
"""

from __future__ import annotations

from dataclasses import dataclass

from motelmg.core.money import percent_of
from motelmg.models import ChargeItem, Quote, QuoteLine, Tax, TaxSummary


@dataclass
class TaxPortion:
    tax: Tax
    amount: int


def taxes_for(amount: int, *, scope: str, kind: str, quantity: int, taxes: list[Tax]) -> list[TaxPortion]:
    """Taxes to post for a line of ``amount`` cents.

    ``scope`` is ``"room"`` for room revenue (room nights and their discounts)
    and ``"extras"`` for everything else. Fixed per-night taxes only apply to
    room night lines (``kind == "room"``).
    """
    portions: list[TaxPortion] = []
    for tax in taxes:
        if not tax.is_active:
            continue
        if tax.kind == "percent":
            if tax.applies_to not in ("all", scope):
                continue
            value = percent_of(amount, tax.value)
        else:
            if kind != "room":
                continue
            value = tax.value * quantity
        if value:
            portions.append(TaxPortion(tax, value))
    return portions


def discounted_amount(rate: int, discount_bp: int) -> int:
    """Negative discount amount for one night at ``rate``."""
    return -percent_of(rate, discount_bp) if discount_bp else 0


def compute_quote(*, nights: int, nightly_rate: int, discount_bp: int, taxes: list[Tax],
                  auto_items: list[ChargeItem], discount_name: str = "", deposit_percent: int = 0) -> Quote:
    lines: list[QuoteLine] = []
    tax_totals: dict[str, int] = {}
    order: list[str] = []

    def add_tax(portions: list[TaxPortion]) -> None:
        for portion in portions:
            if portion.tax.name not in tax_totals:
                order.append(portion.tax.name)
                tax_totals[portion.tax.name] = 0
            tax_totals[portion.tax.name] += portion.amount

    room_total = nightly_rate * nights
    lines.append(QuoteLine(f"{nights} night{'s' if nights != 1 else ''} × rate", room_total, "room"))
    for _ in range(nights):
        add_tax(taxes_for(nightly_rate, scope="room", kind="room", quantity=1, taxes=taxes))

    discount_total = 0
    if discount_bp:
        per_night = discounted_amount(nightly_rate, discount_bp)
        discount_total = per_night * nights
        lines.append(QuoteLine(f"Discount{(' - ' + discount_name) if discount_name else ''}", discount_total,
                               "discount"))
        for _ in range(nights):
            add_tax(taxes_for(per_night, scope="room", kind="discount", quantity=1, taxes=taxes))

    fees_total = 0
    for item in auto_items:
        if item.auto_apply == "per_night":
            amount, count = item.default_amount, nights
        elif item.auto_apply == "per_stay":
            amount, count = item.default_amount, 1
        else:
            continue
        line_total = amount * count
        fees_total += line_total
        lines.append(QuoteLine(item.name + (f" × {count}" if count > 1 else ""), line_total, "fee"))
        if item.taxable:
            for _ in range(count):
                add_tax(taxes_for(amount, scope="extras", kind="fee", quantity=1, taxes=taxes))

    subtotal = room_total + discount_total + fees_total
    tax_list = [TaxSummary(name, tax_totals[name]) for name in order if tax_totals[name]]
    tax_total = sum(t.amount for t in tax_list)
    total = subtotal + tax_total
    deposit = percent_of(total, deposit_percent * 100) if deposit_percent else 0
    return Quote(nights=nights, nightly_rate=nightly_rate, room_total=room_total, discount_total=discount_total,
                 fees_total=fees_total, subtotal=subtotal, taxes=tax_list, tax_total=tax_total, total=total,
                 lines=lines, deposit_suggested=deposit)
