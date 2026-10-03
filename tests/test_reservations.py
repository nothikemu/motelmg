from datetime import datetime, timedelta

import pytest

from motelmg.core.enums import HKStatus, ReservationStatus, ServiceStatus
from motelmg.core.errors import ConflictError, PermissionDenied, ValidationError
from tests.conftest import book, card, cash, login_as, new_guest, room


def at(ctx, days=0, hour=9, minute=0):
    base = datetime(2026, 3, 10)
    ctx.clock.set(base + timedelta(days=days, hours=hour, minutes=minute))


# -- booking conflicts & validation ----------------------------------------------------------
def test_double_booking_is_prevented(ctx):
    g1, g2 = new_guest(ctx, "Ann", "One"), new_guest(ctx, "Bob", "Two")
    book(ctx, g1, "101", nights=3)
    today = ctx.clock.today()
    with pytest.raises(ConflictError, match="already booked by Ann One"):
        book(ctx, g2, "101", arrive=today + timedelta(days=2), nights=2)
    # back-to-back stays are fine (check-out day == next check-in day)
    book(ctx, g2, "101", arrive=today + timedelta(days=3), nights=1)
    assert room(ctx, "101").id not in {r.id for r in ctx.rooms.available_rooms(today, today + timedelta(days=4))}


def test_database_trigger_blocks_overlap_even_without_service_checks(ctx):
    g = new_guest(ctx)
    res_id = book(ctx, g, "101", nights=3)
    res = ctx.reservations.get(res_id)
    with pytest.raises(ConflictError):
        ctx.repo_res.insert({**{k: getattr(res, k) for k in ("guest_id", "room_id", "room_type_id", "nightly_rate")},
                             "confirmation_no": "X1", "status": "confirmed", "check_in_date": "2026-03-11",
                             "check_out_date": "2026-03-12", "created_at": "x", "updated_at": "x"})


@pytest.mark.parametrize("data,field", [
    ({"check_in_date": "2026-03-09", "check_out_date": "2026-03-11"}, "check_in_date"),
    ({"check_in_date": "2026-03-12", "check_out_date": "2026-03-12"}, "check_out_date"),
    ({"check_in_date": "2026-03-12", "check_out_date": "2026-03-10"}, "check_out_date"),
    ({"check_in_date": "not a date", "check_out_date": "2026-03-12"}, "check_in_date"),
    ({"check_in_date": "2026-03-10", "check_out_date": "2026-07-10"}, "check_out_date"),
    ({"adults": 3}, "adults"),
    ({"adults": 0}, "adults"),
    ({"nightly_rate": "abc"}, "nightly_rate"),
    ({"room_id": None}, "room_id"),
    ({"guest_id": None}, "guest_id"),
])
def test_invalid_reservation_input(ctx, data, field):
    payload = {"guest_id": new_guest(ctx), "room_id": room(ctx, "101").id, "check_in_date": "2026-03-10",
               "check_out_date": "2026-03-12", "adults": 1}
    payload.update(data)
    with pytest.raises(ValidationError) as exc:
        ctx.reservations.create(payload)
    assert field in exc.value.field_errors


def test_banned_guest_cannot_book(ctx):
    g = new_guest(ctx, is_banned=True, banned_reason="Damaged room")
    with pytest.raises(ConflictError, match="DO NOT RENT"):
        book(ctx, g)


def test_out_of_service_room_cannot_be_booked(ctx):
    ctx.rooms.set_service_status(room(ctx, "102").id, ServiceStatus.OUT_OF_SERVICE, "Renovation",
                                 until=ctx.clock.today() + timedelta(days=5))
    with pytest.raises(ConflictError, match="out of service"):
        book(ctx, new_guest(ctx), "102")
    # but it can be sold after its expected return date
    book(ctx, new_guest(ctx, "Later", "Guest"), "102", arrive=ctx.clock.today() + timedelta(days=6))


def test_rate_override_requires_permission(ctx):
    g = new_guest(ctx)
    login_as(ctx, "Front Desk")
    with pytest.raises(PermissionDenied):
        book(ctx, g, nightly_rate="50")
    res_id = book(ctx, g, nightly_rate="100.00")  # standard rate is fine
    assert ctx.reservations.get(res_id).nightly_rate == 100_00
    login_as(ctx, "Manager")
    res2 = book(ctx, g, "201", nightly_rate="120")
    assert ctx.reservations.get(res2).rate_overridden


# -- modifications -----------------------------------------------------------------------------
def test_modify_dates_room_and_discount(ctx):
    g = new_guest(ctx)
    res_id = book(ctx, g, "101", nights=2)
    other = book(ctx, new_guest(ctx, "Blocker", "Guest"), "102", arrive=ctx.clock.today() + timedelta(days=3))
    with pytest.raises(ConflictError):
        ctx.reservations.update(res_id, {"room_id": room(ctx, "102").id, "check_out_date": "2026-03-15"})
    discount = ctx.catalog.discount_types()[0]
    ctx.reservations.update(res_id, {"room_id": room(ctx, "201").id, "check_out_date": "2026-03-13",
                                     "discount_id": discount.id, "adults": 3})
    res = ctx.reservations.get(res_id)
    assert (res.room_number, res.nights, res.adults, res.nightly_rate) == ("201", 3, 3, 150_00)
    assert res.discount_bp == discount.percent_bp
    log = ctx.audit.search(entity_type="reservation", entity_id=res_id)
    assert any("room 101 → 201" in e.summary for e in log)
    assert ctx.reservations.get(other).status == ReservationStatus.CONFIRMED


def test_extend_and_shorten_in_house_stay_reposts_nights(ctx):
    res_id = book(ctx, new_guest(ctx), "101", nights=2)
    at(ctx, 0, 15)
    ctx.reservations.check_in(res_id)
    assert ctx.billing.folio(res_id).subtotal == 200_00
    ctx.reservations.update(res_id, {"check_out_date": "2026-03-14"})
    assert ctx.billing.folio(res_id).subtotal == 400_00
    # cannot extend into another reservation
    book(ctx, new_guest(ctx, "Next", "Guest"), "101", arrive=datetime(2026, 3, 14).date(), nights=1)
    with pytest.raises(ConflictError, match="Transfer the guest"):
        ctx.reservations.update(res_id, {"check_out_date": "2026-03-15"})
    ctx.reservations.update(res_id, {"check_out_date": "2026-03-11"})
    folio = ctx.billing.folio(res_id)
    assert folio.subtotal == 100_00 and folio.total == 112_00


def test_closed_reservation_cannot_be_rebooked(ctx):
    res_id = book(ctx, new_guest(ctx), "101")
    ctx.reservations.cancel(res_id, "Changed plans")
    with pytest.raises(ConflictError):
        ctx.reservations.update(res_id, {"check_in_date": "2026-03-20", "check_out_date": "2026-03-21"})
    ctx.reservations.update(res_id, {"special_requests": "Call before arrival"})


# -- cancellations / no-shows ----------------------------------------------------------------
def test_cancellation_with_fee_and_deposit_refund(ctx):
    res_id = book(ctx, new_guest(ctx), "101", arrive=ctx.clock.today() + timedelta(days=5))
    ctx.billing.record_payment(res_id, amount="100", method_id=card(ctx), reference="1111")
    with pytest.raises(ValidationError):
        ctx.reservations.cancel(res_id, "")
    balance = ctx.reservations.cancel(res_id, "Trip cancelled", fee="25")
    assert balance == -75_00  # credit owed to the guest
    assert ctx.reservations.get(res_id).status == ReservationStatus.CANCELLED
    # room released immediately
    book(ctx, new_guest(ctx, "Other", "Guest"), "101", arrive=ctx.clock.today() + timedelta(days=5))
    with pytest.raises(ValidationError):
        ctx.billing.refund(res_id, amount="150", method_id=card(ctx), reason="too much")
    ctx.billing.refund(res_id, amount="75", method_id=card(ctx), reason="Deposit minus fee")
    assert ctx.billing.balance(res_id) == 0
    with pytest.raises(ConflictError):
        ctx.reservations.check_in(res_id)


def test_no_show_and_reinstate(ctx):
    res_id = book(ctx, new_guest(ctx), "101", arrive=ctx.clock.today() + timedelta(days=1))
    with pytest.raises(ConflictError, match="on or after"):
        ctx.reservations.mark_no_show(res_id)
    at(ctx, 1, 23)
    ctx.reservations.mark_no_show(res_id, fee="100")
    res = ctx.reservations.get(res_id)
    assert res.status == ReservationStatus.NO_SHOW and res.balance == 100_00
    ctx.reservations.reinstate(res_id)
    res = ctx.reservations.get(res_id)
    assert res.status == ReservationStatus.CONFIRMED and res.balance == 0  # fee voided


def test_permissions_for_cancellation(ctx):
    res_id = book(ctx, new_guest(ctx), "101")
    login_as(ctx, "Housekeeping")
    with pytest.raises(PermissionDenied):
        ctx.reservations.cancel(res_id, "nope")
    with pytest.raises(PermissionDenied):
        ctx.reservations.check_in(res_id)


# -- check-in variations -------------------------------------------------------------------------
def test_early_check_in_with_fee_and_dirty_room_warning(ctx):
    res_id = book(ctx, new_guest(ctx), "101", nights=1)
    ctx.housekeeping.set_room_status(room(ctx, "101").id, HKStatus.DIRTY, "Spill")
    at(ctx, 0, 10)
    preview = ctx.reservations.check_in_preview(res_id)
    assert preview.early_hours and preview.early_fee_default == 20_00 and preview.room_issue == "dirty"
    with pytest.raises(ConflictError, match="not ready"):
        ctx.reservations.check_in(res_id)
    ctx.reservations.check_in(res_id, allow_dirty=True, early_fee="20")
    folio = ctx.billing.folio(res_id)
    assert any(c.description == "Early check-in" for c in folio.charges)
    assert folio.total == 112_00 + 22_00


def test_arriving_days_early_moves_arrival(ctx):
    res_id = book(ctx, new_guest(ctx), "101", arrive=ctx.clock.today() + timedelta(days=2), nights=1)
    at(ctx, 0, 16)
    preview = ctx.reservations.check_in_preview(res_id)
    assert preview.arrival_shift == "early" and preview.quote.nights == 3
    ctx.reservations.check_in(res_id)
    res = ctx.reservations.get(res_id)
    assert res.check_in_date == ctx.clock.today() and res.nights == 3
    assert ctx.billing.folio(res_id).subtotal == 300_00


def test_late_arrival_is_not_charged_for_missed_night(ctx):
    res_id = book(ctx, new_guest(ctx), "101", nights=3)
    at(ctx, 1, 18)
    assert ctx.reservations.check_in_preview(res_id).arrival_shift == "late"
    ctx.reservations.check_in(res_id)
    assert ctx.reservations.get(res_id).nights == 2
    assert ctx.billing.folio(res_id).subtotal == 200_00


def test_guest_id_required_at_check_in(ctx):
    g = ctx.guests.create({"first_name": "No", "last_name": "Id"})
    res_id = book(ctx, g, "101")
    at(ctx, 0, 15)
    with pytest.raises(ValidationError, match="ID"):
        ctx.reservations.check_in(res_id)
    ctx.guests.update_identity(g, "passport", "X1234567")
    ctx.reservations.check_in(res_id)


def test_cannot_check_in_to_occupied_room(ctx):
    first = book(ctx, new_guest(ctx), "101", nights=1)
    at(ctx, 0, 15)
    ctx.reservations.check_in(first)
    at(ctx, 1, 15)  # first guest overdue, second arrives
    second = book(ctx, new_guest(ctx, "Second", "Guest"), "101", nights=1)
    alerts = {a.key.split(":")[0] for a in ctx.alerts.current()}
    assert {"overdue", "blocked"} <= alerts
    with pytest.raises(ConflictError, match="still occupied"):
        ctx.reservations.check_in(second)


# -- check-out variations -------------------------------------------------------------------------
def test_checkout_requires_payment_unless_manager(ctx):
    res_id = book(ctx, new_guest(ctx), "101", nights=1)
    at(ctx, 0, 15)
    ctx.reservations.check_in(res_id)
    at(ctx, 1, 10)
    with pytest.raises(ConflictError, match="still owes"):
        ctx.reservations.check_out(res_id)
    login_as(ctx, "Front Desk")
    with pytest.raises(PermissionDenied):
        ctx.reservations.check_out(res_id, allow_balance=True)
    # paying as part of check-out works in one step
    ctx.reservations.check_out(res_id, payment={"amount": "112", "method_id": cash(ctx)})
    assert ctx.reservations.get(res_id).status == ReservationStatus.CHECKED_OUT


def test_manager_can_check_out_with_open_balance(ctx):
    res_id = book(ctx, new_guest(ctx), "101", nights=1)
    at(ctx, 0, 15)
    ctx.reservations.check_in(res_id)
    login_as(ctx, "Manager")
    at(ctx, 1, 10)
    ctx.reservations.check_out(res_id, allow_balance=True)
    rows = ctx.billing.outstanding()
    assert [r["id"] for r in rows] == [res_id]
    ctx.billing.record_payment(res_id, amount="112", method_id=cash(ctx))
    with pytest.raises(ConflictError, match="fully paid"):
        ctx.billing.record_payment(res_id, amount="1", method_id=cash(ctx))


def test_early_departure_voids_unused_nights(ctx):
    res_id = book(ctx, new_guest(ctx), "101", nights=4)
    at(ctx, 0, 15)
    ctx.reservations.check_in(res_id)
    ctx.billing.record_payment(res_id, amount="448", method_id=cash(ctx))
    at(ctx, 1, 9)
    preview = ctx.reservations.check_out_preview(res_id)
    assert preview.early_departure and preview.nights_removed == 3 and preview.removed_value == 336_00
    assert preview.estimated_balance == -336_00
    ctx.reservations.check_out(res_id)
    res = ctx.reservations.get(res_id)
    assert res.nights == 1 and res.balance == -336_00
    assert any(a.key == f"credit:{res_id}" for a in ctx.alerts.current())


def test_overdue_guest_charged_extra_night_and_late_fee(ctx):
    res_id = book(ctx, new_guest(ctx), "101", nights=1)
    at(ctx, 0, 15)
    ctx.reservations.check_in(res_id)
    at(ctx, 1, 12)  # 12:00, past 11:00 + 30 min grace
    assert ctx.reservations.is_overdue(ctx.reservations.get(res_id))
    preview = ctx.reservations.check_out_preview(res_id)
    assert preview.late and preview.late_fee_default == 20_00
    ctx.reservations.update(res_id, {"late_checkout_until": "13:00"})
    assert not ctx.reservations.is_overdue(ctx.reservations.get(res_id))
    at(ctx, 2, 10)  # stayed an extra night without telling anyone
    preview = ctx.reservations.check_out_preview(res_id)
    assert preview.extra_nights == 1 and preview.extra_value == 112_00
    ctx.reservations.check_out(res_id, late_fee="20", allow_balance=True)
    folio = ctx.billing.folio(res_id)
    assert folio.subtotal == 200_00 + 20_00 and folio.total == 224_00 + 22_00


# -- room transfers -------------------------------------------------------------------------------
def test_room_transfer_mid_stay(ctx):
    res_id = book(ctx, new_guest(ctx), "101", nights=3)
    at(ctx, 0, 15)
    ctx.reservations.check_in(res_id)
    at(ctx, 1, 10)
    with pytest.raises(ValidationError):
        ctx.reservations.transfer(res_id, room(ctx, "201").id, "")
    ctx.reservations.transfer(res_id, room(ctx, "201").id, "AC broken", use_new_rate=True)
    res = ctx.reservations.get(res_id)
    assert res.room_number == "201" and res.nightly_rate == 150_00
    nights = sorted((c for c in ctx.billing.folio(res_id).charges if c.kind == "room" and not c.is_void),
                    key=lambda c: c.service_date)
    assert [(c.service_date.day, c.amount, c.room_id) for c in nights] == [
        (10, 100_00, room(ctx, "101").id), (11, 150_00, room(ctx, "201").id), (12, 150_00, room(ctx, "201").id)]
    assert room(ctx, "101").hk_status == HKStatus.DIRTY
    assert ctx.reservations.room_moves(res_id)[0].reason == "AC broken"
    # occupied target rooms are rejected
    other = book(ctx, new_guest(ctx, "Occ", "Upant"), "102", nights=2)
    ctx.reservations.check_in(other)
    with pytest.raises(ConflictError, match="booked by Occ Upant"):
        ctx.reservations.transfer(res_id, room(ctx, "102").id, "test")


def test_quote_matches_posted_charges_with_discount_and_auto_fees(ctx):
    resort = ctx.catalog.save_charge_item(None, {"name": "Resort fee", "category": "fee", "default_amount": "5",
                                                 "taxable": True, "auto_apply": "per_night"})
    ctx.catalog.save_charge_item(None, {"name": "Parking pass", "category": "fee", "default_amount": "7.50",
                                        "taxable": False, "auto_apply": "per_stay"})
    discount = ctx.catalog.save_discount(None, {"name": "Promo 15", "percent": "15"})
    g = new_guest(ctx)
    today = ctx.clock.today()
    quote = ctx.reservations.quote(room_id=room(ctx, "201").id, check_in=today,
                                   check_out=today + timedelta(days=3), discount_id=discount)
    res_id = book(ctx, g, "201", nights=3, discount_id=discount)
    at(ctx, 0, 15)
    ctx.reservations.check_in(res_id)
    folio = ctx.billing.folio(res_id)
    assert folio.total == quote.total
    assert folio.subtotal == 3 * 150_00 - 3 * 22_50 + 3 * 5_00 + 7_50
    assert resort
