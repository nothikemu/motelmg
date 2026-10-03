from datetime import datetime, timedelta

import pytest

from motelmg.core.errors import ConflictError, PermissionDenied, ValidationError
from motelmg.reporting.documents import folio_html
from tests.conftest import book, card, cash, login_as, new_guest


def checked_in(ctx, nights=2, number="101"):
    res_id = book(ctx, new_guest(ctx, f"Guest{number}", "Billing"), number, nights=nights)
    ctx.clock.set(datetime(2026, 3, 10, 15))
    ctx.reservations.check_in(res_id)
    return res_id


def test_taxes_are_posted_per_line(ctx):
    res_id = checked_in(ctx)
    folio = ctx.billing.folio(res_id)
    names = {t.name: t.amount for t in folio.taxes}
    assert names == {"Sales tax (10%)": 20_00, "Occupancy tax": 4_00}
    assert folio.subtotal == 200_00 and folio.tax_total == 24_00


def test_no_tax_property(notax_ctx):
    ctx = notax_ctx
    res_id = checked_in(ctx)
    assert ctx.billing.folio(res_id).total == 200_00


def test_charge_validation_and_void(ctx):
    res_id = checked_in(ctx)
    with pytest.raises(ValidationError):
        ctx.billing.post_charge(res_id, {"description": "Snacks", "amount": "0"})
    with pytest.raises(ValidationError):
        ctx.billing.post_charge(res_id, {"description": "", "amount": "5"})
    with pytest.raises(ValidationError):
        ctx.billing.post_charge(res_id, {"description": "Future", "amount": "5", "service_date": "2026-04-01"})
    charge_id = ctx.billing.post_charge(res_id, {"description": "Damaged towel", "amount": "15", "taxable": False})
    assert ctx.billing.folio(res_id).total == 224_00 + 15_00
    room_line = next(c for c in ctx.billing.folio(res_id).charges if c.kind == "room")
    with pytest.raises(ConflictError, match="Room nights"):
        ctx.billing.void_charge(room_line.id, "comp")
    with pytest.raises(ValidationError):
        ctx.billing.void_charge(charge_id, "")
    ctx.billing.void_charge(charge_id, "Found the towel")
    assert ctx.billing.folio(res_id).total == 224_00
    with pytest.raises(ConflictError, match="already void"):
        ctx.billing.void_charge(charge_id, "again")


def test_charges_not_allowed_before_check_in(ctx):
    res_id = book(ctx, new_guest(ctx))
    with pytest.raises(ConflictError, match="deposit"):
        ctx.billing.post_charge(res_id, {"description": "x", "amount": "5"})
    pid = ctx.billing.record_payment(res_id, amount="40", method_id=cash(ctx))
    assert ctx.billing.get_payment(pid).kind == "deposit"


def test_discount_reduces_room_revenue_and_tax(ctx):
    res_id = checked_in(ctx)
    with pytest.raises(PermissionDenied):
        login_as(ctx, "Front Desk")
        ctx.billing.apply_discount(res_id, mode="percent", value="10", reason="Noise complaint")
    ctx.auth.login("admin", "Admin1234")
    with pytest.raises(ValidationError):
        ctx.billing.apply_discount(res_id, mode="amount", value="500", reason="too much")
    ctx.billing.apply_discount(res_id, mode="percent", value="10", reason="Noise complaint")
    folio = ctx.billing.folio(res_id)
    assert folio.subtotal == 180_00 and folio.tax_total == 22_00  # 10% tax on 180 + 2x$2 fixed


def test_payment_rules(ctx):
    res_id = checked_in(ctx)
    with pytest.raises(ValidationError, match="reference"):
        ctx.billing.record_payment(res_id, amount="10", method_id=card(ctx))
    with pytest.raises(ValidationError):
        ctx.billing.record_payment(res_id, amount="-10", method_id=cash(ctx))
    with pytest.raises(ValidationError):
        ctx.billing.record_payment(res_id, amount="10", method_id=None)
    p1 = ctx.billing.record_payment(res_id, amount="100", method_id=cash(ctx))
    p2 = ctx.billing.record_payment(res_id, amount="124", method_id=card(ctx), reference="4242")
    assert ctx.billing.balance(res_id) == 0
    receipts = [ctx.billing.get_payment(p).receipt_no for p in (p1, p2)]
    assert receipts == ["RC-000001", "RC-000002"]
    ctx.billing.void_payment(p1, "Card used instead")
    assert ctx.billing.balance(res_id) == 100_00
    with pytest.raises(ConflictError):
        ctx.billing.void_payment(p1, "again")


def test_refund_limits_and_void_order(ctx):
    res_id = checked_in(ctx)
    pay = ctx.billing.record_payment(res_id, amount="300", method_id=cash(ctx))
    assert ctx.billing.balance(res_id) == -76_00
    login_as(ctx, "Front Desk")
    with pytest.raises(PermissionDenied):
        ctx.billing.refund(res_id, amount="76", method_id=cash(ctx), reason="Overpaid")
    ctx.auth.login("admin", "Admin1234")
    with pytest.raises(ValidationError, match="at most"):
        ctx.billing.refund(res_id, amount="301", method_id=cash(ctx), reason="Overpaid")
    refund = ctx.billing.refund(res_id, amount="76", method_id=cash(ctx), reason="Overpaid")
    assert ctx.billing.balance(res_id) == 0
    ctx.billing.refund(res_id, amount="224", method_id=cash(ctx), reason="Full comp")
    with pytest.raises(ConflictError, match="refund"):
        ctx.billing.void_payment(pay, "mistake")
    ctx.billing.void_payment(refund, "Entered twice")


def test_invoice_numbers_and_document(ctx):
    a = checked_in(ctx, nights=1, number="101")
    b = checked_in(ctx, nights=1, number="102")
    ctx.clock.set(datetime(2026, 3, 11, 10))
    for res_id in (a, b):
        ctx.reservations.check_out(res_id, payment={"amount": "112", "method_id": cash(ctx)})
    assert ctx.billing.folio(a).invoice_no == "INV-000001"
    assert ctx.billing.folio(b).invoice_no == "INV-000002"
    assert ctx.billing.issue_invoice(a) == "INV-000001"  # never re-numbered
    ctx.billing.post_charge(a, {"description": "Damage found after departure", "amount": "40", "taxable": False})
    html = folio_html(ctx, ctx.billing.folio(a))
    assert "Balance due" in html and "$40.00" in html
    assert len(ctx.billing.invoices()) == 2
    assert {r["id"] for r in ctx.billing.outstanding()} == {a}
    assert ctx.clock.today() - timedelta(days=1)
