"""End-to-end front desk workflow, exactly as a motel employee performs it:

guest -> reservation -> room assignment -> check-in -> charges -> payment ->
check-out -> receipt -> housekeeping -> inspection -> room available again.
"""

from datetime import datetime, timedelta

from motelmg.core.enums import HKStatus, ReservationStatus, RoomState, TaskStatus
from motelmg.reporting.documents import folio_html, payment_receipt_html, registration_card_html
from tests.conftest import book, card, cash, new_guest, room


def board_state(ctx, number):
    return next(i for i in ctx.rooms.board() if i.room.number == number).state


def test_complete_guest_lifecycle(ctx):
    # 1. Create the guest profile
    guest_id = new_guest(ctx, "Jane", "Doe", city="Denver", vehicle_plate="abc123")
    guest = ctx.guests.get(guest_id)
    assert guest.full_name == "Jane Doe" and guest.vehicle_plate == "ABC123"

    # 2. Make a reservation (quote first, as the booking screen does)
    today = ctx.clock.today()
    quote = ctx.reservations.quote(room_id=room(ctx, "101").id, check_in=today, check_out=today + timedelta(days=2))
    assert quote.room_total == 200_00 and quote.tax_total == 24_00 and quote.total == 224_00
    res_id = book(ctx, guest_id, "102", nights=2, expected_arrival="14:00")
    res = ctx.reservations.get(res_id)
    assert res.status == ReservationStatus.CONFIRMED and res.confirmation_no == "R10001"
    assert board_state(ctx, "102") == RoomState.RESERVED

    # 3. Reassign to another room before arrival
    ctx.reservations.transfer(res_id, room(ctx, "101").id, "Guest prefers room near office")
    assert ctx.reservations.get(res_id).room_number == "101"
    assert board_state(ctx, "102") == RoomState.AVAILABLE

    # 4. Take a deposit, then check in at 3 PM
    ctx.billing.record_payment(res_id, amount="50", method_id=card(ctx), reference="4242")
    ctx.clock.set(datetime.combine(today, datetime.min.time()).replace(hour=15, minute=5))
    preview = ctx.reservations.check_in_preview(res_id)
    assert preview.room_issue == "" and not preview.early_hours and preview.deposits == 50_00
    ctx.reservations.check_in(res_id)
    res = ctx.reservations.get(res_id)
    assert res.status == ReservationStatus.CHECKED_IN and res.actual_check_in is not None
    folio = ctx.billing.folio(res_id)
    assert folio.total == quote.total == 224_00  # posted charges match the quote exactly
    assert board_state(ctx, "101") == RoomState.OCCUPIED
    assert "Jane Doe" in registration_card_html(ctx, res_id)

    # 5. Add an extra charge during the stay
    laundry = next(i for i in ctx.catalog.charge_items() if i.name == "Laundry")
    ctx.billing.post_charge(res_id, {"item_id": laundry.id, "amount": "8.00", "quantity": 1})
    assert ctx.billing.folio(res_id).total == 232_80

    # 6. Process payment of the balance
    balance = ctx.billing.balance(res_id)
    assert balance == 182_80
    pay_id = ctx.billing.record_payment(res_id, amount="182.80", method_id=cash(ctx))
    assert ctx.billing.balance(res_id) == 0
    assert "PAYMENT RECEIPT" in payment_receipt_html(ctx, ctx.billing.get_payment(pay_id))

    # 7. Check out on the departure morning
    ctx.clock.set(ctx.clock.now() + timedelta(days=2) - timedelta(hours=5))  # day+2, 10:05
    preview = ctx.reservations.check_out_preview(res_id)
    assert not preview.late and not preview.early_departure and preview.estimated_balance == 0
    invoice_no = ctx.reservations.check_out(res_id)
    assert invoice_no == "INV-000001"
    res = ctx.reservations.get(res_id)
    assert res.status == ReservationStatus.CHECKED_OUT and res.balance == 0

    # 8. Generate the receipt / invoice
    html = folio_html(ctx, ctx.billing.folio(res_id))
    assert "INVOICE" in html and "INV-000001" in html and "Laundry" in html and "$232.80" in html

    # 9. Room goes to housekeeping automatically
    r101 = room(ctx, "101")
    assert r101.hk_status == HKStatus.DIRTY
    assert board_state(ctx, "101") == RoomState.VACANT_DIRTY
    task = ctx.housekeeping.tasks(statuses=["pending"], room_id=r101.id)[0]
    assert task.task_type == "checkout"

    # 10. Clean and inspect the room
    maid = ctx.users.housekeepers()[0].id
    ctx.housekeeping.assign([task.id], maid)
    ctx.housekeeping.start(task.id)
    assert room(ctx, "101").hk_status == HKStatus.CLEANING
    ctx.housekeeping.complete(task.id, "All good")
    assert room(ctx, "101").hk_status == HKStatus.CLEAN
    ctx.housekeeping.inspect(task.id, True)
    assert room(ctx, "101").hk_status == HKStatus.INSPECTED
    assert ctx.housekeeping.get(task.id).status == TaskStatus.INSPECTED

    # 11. Available for the next guest
    assert board_state(ctx, "101") == RoomState.AVAILABLE
    today = ctx.clock.today()
    assert any(r.number == "101" for r in ctx.rooms.available_rooms(today, today + timedelta(days=1)))
    next_res = book(ctx, new_guest(ctx, "John", "Next"), "101", nights=1)
    assert ctx.reservations.get(next_res).status == ReservationStatus.CONFIRMED

    # Every step is in the audit trail
    actions = [e.action for e in ctx.audit.search(entity_type="reservation", entity_id=res_id)]
    for action in ("reservations.create", "reservations.transfer", "billing.deposit", "reservations.check_in",
                   "billing.charge", "billing.payment", "reservations.check_out", "billing.invoice"):
        assert action in actions, action


def test_walk_in_with_immediate_payment(ctx):
    guest_id = new_guest(ctx, "Walter", "Inn")
    ctx.clock.set(ctx.clock.now().replace(hour=21))
    res_id = ctx.reservations.walk_in({"guest_id": guest_id, "room_id": room(ctx, "201").id, "nights": 1,
                                       "adults": 3}, payment={"amount": "167", "method_id": cash(ctx)})
    res = ctx.reservations.get(res_id)
    assert res.status == ReservationStatus.CHECKED_IN and res.is_walk_in and res.source == "walk_in"
    assert ctx.billing.folio(res_id).total == 150_00 + 15_00 + 2_00
    assert ctx.billing.balance(res_id) == 0
