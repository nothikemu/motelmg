"""Reservations and the front desk workflows: booking, modification, check-in,
check-out, room transfers, walk-ins, cancellations and no-shows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from motelmg.core import validation as v
from motelmg.core.dates import nights_between, parse_date, parse_time
from motelmg.core.enums import HKStatus, ReservationSource, ReservationStatus as RS, ServiceStatus
from motelmg.core.errors import ConflictError, NotFoundError, ValidationError
from motelmg.core.money import parse_amount
from motelmg.models import Folio, Guest, Quote, Reservation, Room
from motelmg.services.rooms import departure_overdue


@dataclass
class CheckInPreview:
    reservation: Reservation
    guest: Guest
    room: Room
    arrival_shift: str = ""  # "", "early" (arriving before booked date) or "late"
    new_check_in: date | None = None
    early_hours: bool = False  # before the standard check-in time
    early_fee_default: int = 0
    room_issue: str = ""  # "", dirty, cleaning, not_inspected, out_of_service, occupied, inactive
    occupied_by: Reservation | None = None
    id_required: bool = False
    missing_id: bool = False
    quote: Quote | None = None
    deposits: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return self.room_issue in ("out_of_service", "occupied", "inactive")


@dataclass
class CheckOutPreview:
    reservation: Reservation
    folio: Folio
    early_departure: bool = False
    new_check_out: date | None = None
    nights_removed: int = 0
    removed_value: int = 0
    extra_nights: int = 0
    extra_value: int = 0
    late: bool = False
    late_fee_default: int = 0
    estimated_balance: int = 0


def _fmt_date(d: date) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ")


class ReservationService:
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def repo(self):
        return self.ctx.repo_res

    # -- queries ----------------------------------------------------------------------
    def get(self, res_id: int) -> Reservation:
        res = self.repo.get(res_id)
        if not res:
            raise NotFoundError("Reservation not found.")
        return res

    def find(self, confirmation_no: str) -> Reservation | None:
        return self.repo.get_by_confirmation(confirmation_no.strip())

    def search(self, **filters) -> list[Reservation]:
        self.ctx.require("reservations.view")
        return self.repo.search(**filters)

    def arrivals(self, day: date | None = None) -> list[Reservation]:
        day = day or self.ctx.clock.today()
        result = self.repo.arrivals_on(day)
        if day == self.ctx.clock.today():
            seen = {r.id for r in result}
            result += [r for r in self.repo.stale_confirmed(day) if r.id not in seen and r.check_out_date > day]
        return result

    def departures(self, day: date | None = None) -> list[Reservation]:
        return self.repo.departures_on(day or self.ctx.clock.today())

    def in_house(self) -> list[Reservation]:
        return self.repo.in_house()

    def is_overdue(self, res: Reservation) -> bool:
        settings = self.ctx.settings
        return departure_overdue(res, self.ctx.clock.now(), settings.check_out_time(),
                                 settings.get_int("policy.late_checkout_grace_minutes"))

    def room_moves(self, res_id: int):
        return self.repo.room_moves(res_id)

    def quote(self, *, room_id: int | None = None, check_in: Any, check_out: Any, nightly_rate: Any = None,
              discount_id: int | None = None) -> Quote:
        ci = parse_date(check_in, field="check_in_date", label="Arrival")
        co = parse_date(check_out, field="check_out_date", label="Departure")
        nights = max(nights_between(ci, co), 0)
        if nightly_rate in (None, ""):
            rate = self.ctx.rooms.get(room_id).effective_rate if room_id else 0
        else:
            rate = parse_amount(nightly_rate, field="nightly_rate", label="Rate")
        name, bp = self._discount(discount_id)
        return self.ctx.billing.quote(nights=nights, nightly_rate=rate, discount_bp=bp, discount_name=name)

    def _discount(self, discount_id: Any) -> tuple[str, int]:
        if not discount_id:
            return "", 0
        for d in self.ctx.repo_folio.discount_types(include_inactive=True):
            if d.id == int(discount_id):
                return d.name, d.percent_bp
        raise ValidationError("Select a valid discount.", field="discount_id")

    # -- validation helpers -------------------------------------------------------------
    def _parse_stay(self, data: dict[str, Any], *, allow_past_arrival: bool = False,
                    original: Reservation | None = None) -> tuple[date, date]:
        errors: dict[str, str] = {}
        try:
            ci = parse_date(data.get("check_in_date"), field="check_in_date", label="Arrival date")
        except ValidationError as exc:
            errors.update(exc.field_errors)
            ci = None
        try:
            co = parse_date(data.get("check_out_date"), field="check_out_date", label="Departure date")
        except ValidationError as exc:
            errors.update(exc.field_errors)
            co = None
        if errors:
            raise ValidationError(field_errors=errors)
        assert ci and co
        today = self.ctx.clock.today()
        settings = self.ctx.settings
        if co <= ci:
            raise ValidationError("Departure must be after arrival (at least one night).", field="check_out_date")
        if ci < today and not allow_past_arrival and not (original and original.check_in_date == ci):
            raise ValidationError("Arrival date cannot be in the past.", field="check_in_date")
        max_nights = settings.get_int("policy.max_nights")
        if nights_between(ci, co) > max_nights:
            raise ValidationError(f"Stays are limited to {max_nights} nights. Split longer stays into "
                                  "several reservations or change the limit in Settings.", field="check_out_date")
        horizon = settings.get_int("policy.booking_horizon_days")
        if ci > today + timedelta(days=horizon):
            raise ValidationError(f"Reservations can be made up to {horizon} days ahead.", field="check_in_date")
        return ci, co

    def _check_room(self, room: Room, ci: date, co: date, guests: int, exclude_id: int | None = None) -> None:
        if not room.is_active:
            raise ValidationError(f"Room {room.number} is archived and cannot be booked.", field="room_id")
        if not self.ctx.rooms.sellable_for(room, ci):
            reason = f" ({room.service_reason})" if room.service_reason else ""
            until = f" until {_fmt_date(room.service_until)}" if room.service_until else ""
            raise ConflictError(f"Room {room.number} is {ServiceStatus.LABELS[room.service_status].lower()}"
                                f"{until}{reason}. Choose another room.")
        if guests > room.capacity:
            raise ValidationError(f"Room {room.number} sleeps at most {room.capacity} guests.", field="adults")
        conflicts = self.repo.conflicts(room.id, ci, co, exclude_id)
        if conflicts:
            c = conflicts[0]
            raise ConflictError(
                f"Room {room.number} is already booked by {c.guest_name} ({c.confirmation_no}) from "
                f"{_fmt_date(c.check_in_date)} to {_fmt_date(c.check_out_date)}. Choose another room or dates.")

    def _guests(self, data: dict[str, Any]) -> tuple[int, int]:
        errors: dict[str, str] = {}
        adults = children = 0
        try:
            adults = v.int_range(data.get("adults", 1), "Adults", "adults", 1, 20)
        except ValidationError as exc:
            errors.update(exc.field_errors)
        try:
            children = v.int_range(data.get("children", 0) or 0, "Children", "children", 0, 20)
        except ValidationError as exc:
            errors.update(exc.field_errors)
        if errors:
            raise ValidationError(field_errors=errors)
        return adults, children

    def _rate(self, data: dict[str, Any], room: Room, current: int | None = None) -> tuple[int, bool]:
        raw = data.get("nightly_rate")
        default = room.effective_rate
        if raw in (None, ""):
            return (current if current is not None else default), False
        rate = parse_amount(raw, field="nightly_rate", label="Nightly rate")
        if rate != default and rate != current:
            self.ctx.require("reservations.override_rate")
        return rate, rate != default

    @staticmethod
    def _time_text(value: Any, field_name: str, label: str) -> str:
        text = v.clean(value)
        if not text:
            return ""
        return parse_time(text, field=field_name, label=label).strftime("%H:%M")

    # -- create --------------------------------------------------------------------------
    def create(self, data: dict[str, Any], *, _walk_in: bool = False) -> int:
        self.ctx.require("reservations.create")
        guest_id = data.get("guest_id")
        if not guest_id:
            raise ValidationError("Select or create a guest.", field="guest_id")
        guest = self.ctx.guests.ensure_bookable(int(guest_id))
        ci, co = self._parse_stay(data)
        if not data.get("room_id"):
            raise ValidationError("Select a room.", field="room_id")
        room = self.ctx.rooms.get(int(data["room_id"]))
        adults, children = self._guests(data)
        self._check_room(room, ci, co, adults + children)
        rate, overridden = self._rate(data, room)
        discount_name, discount_bp = self._discount(data.get("discount_id"))
        source = data.get("source") or (ReservationSource.WALK_IN if _walk_in else ReservationSource.PHONE)
        if source not in ReservationSource.LABELS:
            raise ValidationError("Select a booking source.", field="source")
        values = {
            "guest_id": guest.id, "room_id": room.id, "room_type_id": room.room_type_id,
            "check_in_date": ci.isoformat(), "check_out_date": co.isoformat(),
            "adults": adults, "children": children, "status": RS.CONFIRMED, "source": source,
            "is_walk_in": int(_walk_in), "nightly_rate": rate, "rate_overridden": int(overridden),
            "discount_name": discount_name, "discount_bp": discount_bp,
            "expected_arrival": self._time_text(data.get("expected_arrival"), "expected_arrival", "Arrival time"),
            "late_checkout_until": self._time_text(data.get("late_checkout_until"), "late_checkout_until",
                                                   "Late check-out time"),
            "special_requests": v.optional(data.get("special_requests"), "Special requests", "special_requests",
                                           max_len=1000),
            "created_by": self.ctx.user_id, "created_at": self.ctx.now_str(), "updated_at": self.ctx.now_str(),
        }
        note = v.optional(data.get("note"), "Note", "note", max_len=2000)
        with self.ctx.db.transaction():
            number = self.ctx.db.next_counter("reservation")
            values["confirmation_no"] = f"{self.ctx.settings.get_str('numbering.reservation_prefix')}{number}"
            res_id = self.repo.insert(values)
            if note:
                self.ctx.repo_notes.add(body=note, important=False, user_id=self.ctx.user_id,
                                        ts=self.ctx.now_str(), reservation_id=res_id)
            self.ctx.audit.log(
                "reservations.walk_in" if _walk_in else "reservations.create", "reservation", res_id,
                f"{'Walk-in' if _walk_in else 'Reservation'} {values['confirmation_no']} for {guest.full_name}: "
                f"room {room.number}, {_fmt_date(ci)} → {_fmt_date(co)} ({nights_between(ci, co)} nights) "
                f"at {self.ctx.settings.money(rate)}",
                {"rate_overridden": overridden, "discount": discount_name})
        self.ctx.events.emit("reservations", "rooms")
        return res_id

    # -- update --------------------------------------------------------------------------
    def update(self, res_id: int, data: dict[str, Any]) -> None:
        self.ctx.require("reservations.edit")
        res = self.get(res_id)
        changes: dict[str, tuple[Any, Any]] = {}
        values: dict[str, Any] = {}

        def track(key: str, old: Any, new: Any) -> None:
            if old != new:
                changes[key] = (old, new)
                values[key] = new

        if "special_requests" in data:
            track("special_requests", res.special_requests,
                  v.optional(data.get("special_requests"), "Special requests", "special_requests", max_len=1000))

        if res.status == RS.CONFIRMED:
            guest_id = int(data.get("guest_id") or res.guest_id)
            if guest_id != res.guest_id:
                self.ctx.guests.ensure_bookable(guest_id)
            track("guest_id", res.guest_id, guest_id)
            ci, co = self._parse_stay({**{"check_in_date": res.check_in_date, "check_out_date": res.check_out_date},
                                       **{k: data[k] for k in ("check_in_date", "check_out_date") if k in data}},
                                      original=res)
            room = self.ctx.rooms.get(int(data.get("room_id") or res.room_id))
            adults, children = self._guests({"adults": data.get("adults", res.adults),
                                             "children": data.get("children", res.children)})
            self._check_room(room, ci, co, adults + children, exclude_id=res.id)
            track("check_in_date", res.check_in_date.isoformat(), ci.isoformat())
            track("check_out_date", res.check_out_date.isoformat(), co.isoformat())
            track("room_id", res.room_id, room.id)
            track("room_type_id", res.room_type_id, room.room_type_id)
            track("adults", res.adults, adults)
            track("children", res.children, children)
            if "nightly_rate" in data or room.id != res.room_id:
                raw = data.get("nightly_rate")
                rate, overridden = self._rate({"nightly_rate": raw}, room, current=res.nightly_rate)
                if raw in (None, "") and room.id != res.room_id and not res.rate_overridden:
                    rate, overridden = room.effective_rate, False
                track("nightly_rate", res.nightly_rate, rate)
                track("rate_overridden", int(res.rate_overridden), int(overridden))
            if "discount_id" in data:
                name, bp = self._discount(data.get("discount_id"))
                track("discount_name", res.discount_name, name)
                track("discount_bp", res.discount_bp, bp)
            if "source" in data and data["source"] in ReservationSource.LABELS:
                track("source", res.source, data["source"])
            if "expected_arrival" in data:
                track("expected_arrival", res.expected_arrival,
                      self._time_text(data.get("expected_arrival"), "expected_arrival", "Arrival time"))
            if "late_checkout_until" in data:
                track("late_checkout_until", res.late_checkout_until,
                      self._time_text(data.get("late_checkout_until"), "late_checkout_until", "Late check-out"))
        elif res.status == RS.CHECKED_IN:
            today = self.ctx.clock.today()
            if "check_out_date" in data:
                co = parse_date(data["check_out_date"], field="check_out_date", label="Departure date")
                if co <= res.check_in_date:
                    raise ValidationError("Departure must be after the arrival date.", field="check_out_date")
                if co < today:
                    raise ValidationError("Departure cannot be in the past.", field="check_out_date")
                if nights_between(res.check_in_date, co) > self.ctx.settings.get_int("policy.max_nights"):
                    raise ValidationError("The stay would exceed the maximum number of nights.",
                                          field="check_out_date")
                if co > res.check_out_date:
                    room = self.ctx.rooms.get(res.room_id)
                    conflicts = self.repo.conflicts(room.id, res.check_out_date, co, res.id)
                    if conflicts:
                        c = conflicts[0]
                        raise ConflictError(
                            f"Room {room.number} is booked by {c.guest_name} ({c.confirmation_no}) from "
                            f"{_fmt_date(c.check_in_date)}. Transfer the guest to another room to extend the stay.")
                track("check_out_date", res.check_out_date.isoformat(), co.isoformat())
            adults, children = self._guests({"adults": data.get("adults", res.adults),
                                             "children": data.get("children", res.children)})
            room = self.ctx.rooms.get(res.room_id)
            if adults + children > room.capacity:
                raise ValidationError(f"Room {room.number} sleeps at most {room.capacity} guests.", field="adults")
            track("adults", res.adults, adults)
            track("children", res.children, children)
            if "late_checkout_until" in data:
                track("late_checkout_until", res.late_checkout_until,
                      self._time_text(data.get("late_checkout_until"), "late_checkout_until", "Late check-out"))
            if data.get("nightly_rate") not in (None, ""):
                rate, overridden = self._rate({"nightly_rate": data["nightly_rate"]}, room, current=res.nightly_rate)
                track("nightly_rate", res.nightly_rate, rate)
                track("rate_overridden", int(res.rate_overridden), int(overridden))
            if "discount_id" in data:
                name, bp = self._discount(data.get("discount_id"))
                track("discount_name", res.discount_name, name)
                track("discount_bp", res.discount_bp, bp)
        else:
            extra = set(data) - {"special_requests"}
            if any(data.get(k) not in (None, "") and str(data.get(k)) != str(getattr(res, k, "")) for k in extra
                   if k in ("check_in_date", "check_out_date", "room_id", "guest_id")):
                raise ConflictError(f"This reservation is {RS.LABELS[res.status].lower()} and can no longer be "
                                    "changed (only special requests and notes).")
        if not values:
            return
        values["updated_at"] = self.ctx.now_str()
        with self.ctx.db.transaction():
            self.repo.update(res.id, values)
            if res.status == RS.CHECKED_IN:
                if any(k in changes for k in ("nightly_rate", "discount_bp")):
                    self.ctx.billing._void_nights_from(res.id, self.ctx.clock.today(), "Rate changed")
                self.ctx.billing._sync_room_nights(res.id, "Stay dates changed")
            summary = ", ".join(self._describe_change(k, old, new) for k, (old, new) in changes.items()
                                if k not in ("room_type_id", "rate_overridden", "updated_at"))
            self.ctx.audit.log("reservations.update", "reservation", res.id,
                               f"Modified {res.confirmation_no}: {summary}",
                               {k: {"from": o, "to": n} for k, (o, n) in changes.items()})
        self.ctx.events.emit("reservations", "rooms", "billing")

    def _describe_change(self, key: str, old: Any, new: Any) -> str:
        money = self.ctx.settings.money
        if key == "room_id":
            old_room = self.ctx.repo_rooms.get_room(old)
            new_room = self.ctx.repo_rooms.get_room(new)
            return f"room {old_room.number if old_room else old} → {new_room.number if new_room else new}"
        if key == "nightly_rate":
            return f"rate {money(old)} → {money(new)}"
        if key in ("check_in_date", "check_out_date"):
            label = "arrival" if key == "check_in_date" else "departure"
            return f"{label} {old} → {new}"
        if key == "guest_id":
            return "guest changed"
        return key.replace("_", " ")

    # -- cancellation / no-show ----------------------------------------------------------
    def cancel(self, res_id: int, reason: str, fee: Any = None) -> int:
        """Cancel a confirmed reservation. Returns the folio balance afterwards
        (negative = money to refund)."""
        self.ctx.require("reservations.cancel")
        res = self.get(res_id)
        if res.status != RS.CONFIRMED:
            raise ConflictError(f"Only confirmed reservations can be cancelled (this one is "
                                f"{RS.LABELS[res.status].lower()}).")
        reason = v.required(reason, "Cancellation reason", "reason", max_len=300)
        fee_cents = parse_amount(fee, field="fee", label="Cancellation fee") if fee not in (None, "") else 0
        with self.ctx.db.transaction():
            self.repo.update(res.id, {"status": RS.CANCELLED, "cancelled_at": self.ctx.now_str(),
                                      "cancelled_by": self.ctx.user_id, "cancel_reason": reason,
                                      "updated_at": self.ctx.now_str()})
            res.status = RS.CANCELLED
            if fee_cents:
                self.ctx.billing._post_system_fee(res, "CANCELLATION", fee_cents)
            self.ctx.audit.log("reservations.cancel", "reservation", res.id,
                               f"Cancelled {res.confirmation_no} ({res.guest_name}): {reason}"
                               + (f"; fee {self.ctx.settings.money(fee_cents)}" if fee_cents else ""))
        self.ctx.events.emit("reservations", "rooms", "billing")
        return self.ctx.billing.balance(res.id)

    def mark_no_show(self, res_id: int, fee: Any = None) -> int:
        self.ctx.require("reservations.cancel")
        res = self.get(res_id)
        if res.status != RS.CONFIRMED:
            raise ConflictError("Only confirmed reservations can be marked as no-show.")
        if res.check_in_date > self.ctx.clock.today():
            raise ConflictError("A reservation can be marked as no-show on or after its arrival date.")
        fee_cents = parse_amount(fee, field="fee", label="No-show fee") if fee not in (None, "") else 0
        with self.ctx.db.transaction():
            self.repo.update(res.id, {"status": RS.NO_SHOW, "cancelled_at": self.ctx.now_str(),
                                      "cancelled_by": self.ctx.user_id, "cancel_reason": "No-show",
                                      "updated_at": self.ctx.now_str()})
            res.status = RS.NO_SHOW
            if fee_cents:
                self.ctx.billing._post_system_fee(res, "NO_SHOW", fee_cents)
            self.ctx.audit.log("reservations.no_show", "reservation", res.id,
                               f"Marked {res.confirmation_no} ({res.guest_name}) as no-show"
                               + (f"; fee {self.ctx.settings.money(fee_cents)}" if fee_cents else ""))
        self.ctx.events.emit("reservations", "rooms", "billing")
        return self.ctx.billing.balance(res.id)

    def reinstate(self, res_id: int) -> None:
        self.ctx.require("reservations.edit", "reservations.cancel")
        res = self.get(res_id)
        if res.status not in (RS.CANCELLED, RS.NO_SHOW):
            raise ConflictError("Only cancelled or no-show reservations can be reinstated.")
        today = self.ctx.clock.today()
        if res.check_in_date < today:
            raise ConflictError("The arrival date has passed. Create a new reservation instead.")
        room = self.ctx.rooms.get(res.room_id)
        self._check_room(room, res.check_in_date, res.check_out_date, res.guests_count, exclude_id=res.id)
        with self.ctx.db.transaction():
            for charge_id in self.ctx.repo_folio.system_fee_ids(res.id, ("CANCELLATION", "NO_SHOW")):
                self.ctx.billing._void_tree(charge_id, "Reservation reinstated")
            self.repo.update(res.id, {"status": RS.CONFIRMED, "cancelled_at": None, "cancelled_by": None,
                                      "cancel_reason": "", "updated_at": self.ctx.now_str()})
            self.ctx.audit.log("reservations.reinstate", "reservation", res.id,
                               f"Reinstated {res.confirmation_no} ({res.guest_name})")
        self.ctx.events.emit("reservations", "rooms", "billing")

    # -- check-in -------------------------------------------------------------------------
    def check_in_preview(self, res_id: int) -> CheckInPreview:
        res = self.get(res_id)
        guest = self.ctx.guests.get(res.guest_id)
        room = self.ctx.rooms.get(res.room_id)
        now = self.ctx.clock.now()
        today = now.date()
        settings = self.ctx.settings
        p = CheckInPreview(reservation=res, guest=guest, room=room)
        if res.check_in_date > today:
            p.arrival_shift, p.new_check_in = "early", today
            p.warnings.append(f"This reservation arrives {_fmt_date(res.check_in_date)}. Checking in now moves the "
                              f"arrival to today and adds {(res.check_in_date - today).days} night(s).")
        elif res.check_in_date < today:
            p.arrival_shift, p.new_check_in = "late", today
            p.warnings.append(f"Arrival was due {_fmt_date(res.check_in_date)}. The stay will start today; the "
                              "missed night(s) will not be charged.")
        ci_time = datetime.combine(today, settings.check_in_time())
        grace = timedelta(minutes=settings.get_int("policy.early_checkin_grace_minutes"))
        if now < ci_time - grace:
            p.early_hours = True
            item = self.ctx.repo_folio.charge_item_by_code("EARLY_CHECKIN")
            p.early_fee_default = item.default_amount if item else 0
        occupant = self.repo.in_house_for_room(room.id)
        if not room.is_active:
            p.room_issue = "inactive"
        elif room.service_status != ServiceStatus.IN_SERVICE:
            p.room_issue = "out_of_service"
        elif occupant and occupant.id != res.id:
            p.room_issue, p.occupied_by = "occupied", occupant
        elif room.hk_status == HKStatus.DIRTY:
            p.room_issue = "dirty"
        elif room.hk_status == HKStatus.CLEANING:
            p.room_issue = "cleaning"
        elif settings.get_bool("policy.require_inspection") and room.hk_status != HKStatus.INSPECTED:
            p.room_issue = "not_inspected"
        p.id_required = settings.get_bool("policy.require_guest_id")
        p.missing_id = not guest.id_number
        start = p.new_check_in or res.check_in_date
        if res.check_out_date > start:
            p.quote = self.ctx.billing.quote(nights=nights_between(start, res.check_out_date),
                                             nightly_rate=res.nightly_rate, discount_bp=res.discount_bp,
                                             discount_name=res.discount_name)
        p.deposits = self.ctx.repo_folio.paid_total(res.id)
        if guest.is_banned:
            p.warnings.append(f"{guest.full_name} is flagged DO NOT RENT.")
        return p

    def check_in(self, res_id: int, *, allow_dirty: bool = False, early_fee: Any = None,
                 payment: dict[str, Any] | None = None) -> None:
        self.ctx.require("reservations.checkin")
        res = self.get(res_id)
        if res.status != RS.CONFIRMED:
            raise ConflictError(f"Only confirmed reservations can be checked in (this one is "
                                f"{RS.LABELS[res.status].lower()}).")
        guest = self.ctx.guests.ensure_bookable(res.guest_id)
        today = self.ctx.clock.today()
        if res.check_out_date <= today:
            raise ConflictError("The stay dates have already passed. Change the departure date first.")
        room = self.ctx.rooms.get(res.room_id)
        if not room.is_active or room.service_status != ServiceStatus.IN_SERVICE:
            raise ConflictError(f"Room {room.number} is {ServiceStatus.LABELS[room.service_status].lower()}. "
                                "Assign a different room before checking in.")
        occupant = self.repo.in_house_for_room(room.id)
        if occupant:
            raise ConflictError(f"Room {room.number} is still occupied by {occupant.guest_name} "
                                f"({occupant.confirmation_no}). Check them out or assign a different room.")
        not_ready = room.hk_status in (HKStatus.DIRTY, HKStatus.CLEANING) or (
            self.ctx.settings.get_bool("policy.require_inspection") and room.hk_status != HKStatus.INSPECTED)
        if not_ready and not allow_dirty:
            raise ConflictError(f"Room {room.number} is {HKStatus.LABELS[room.hk_status].lower()} and not ready. "
                                "Choose another room or confirm checking in anyway.")
        if self.ctx.settings.get_bool("policy.require_guest_id") and not guest.id_number:
            raise ValidationError("Record the guest's ID document before check-in (required by policy).",
                                  field="id_number")
        fee_cents = parse_amount(early_fee, field="early_fee", label="Early check-in fee") \
            if early_fee not in (None, "") else 0
        with self.ctx.db.transaction():
            values: dict[str, Any] = {"status": RS.CHECKED_IN, "actual_check_in": self.ctx.now_str(),
                                      "checked_in_by": self.ctx.user_id, "updated_at": self.ctx.now_str()}
            if res.check_in_date != today:
                if res.check_in_date > today:
                    conflicts = self.repo.conflicts(room.id, today, res.check_in_date, res.id)
                    if conflicts:
                        raise ConflictError(f"Room {room.number} is booked by {conflicts[0].guest_name} before this "
                                            "guest's original arrival date. Assign another room to check in early.")
                values["check_in_date"] = today.isoformat()
            self.repo.update(res.id, values)
            res = self.get(res.id)
            self.ctx.billing._sync_room_nights(res.id, "Check-in")
            self.ctx.billing._post_stay_fees(res, today)
            if fee_cents:
                self.ctx.billing._post_system_fee(res, "EARLY_CHECKIN", fee_cents)
            if payment and payment.get("amount") not in (None, "", 0, "0"):
                self.ctx.billing.record_payment(res.id, amount=payment["amount"], method_id=payment.get("method_id"),
                                                reference=payment.get("reference", ""))
            self.ctx.audit.log("reservations.check_in", "reservation", res.id,
                               f"Checked in {guest.full_name} to room {room.number} ({res.confirmation_no})"
                               + (" — room not clean" if not_ready else ""))
        self.ctx.events.emit("reservations", "rooms", "billing", "housekeeping")

    def walk_in(self, data: dict[str, Any], *, allow_dirty: bool = False,
                payment: dict[str, Any] | None = None) -> int:
        self.ctx.require("reservations.create", "reservations.checkin")
        today = self.ctx.clock.today()
        nights = v.int_range(data.get("nights", 1), "Nights", "nights", 1,
                             self.ctx.settings.get_int("policy.max_nights"))
        payload = dict(data)
        payload["check_in_date"] = today.isoformat()
        payload["check_out_date"] = (today + timedelta(days=nights)).isoformat()
        payload.setdefault("source", ReservationSource.WALK_IN)
        with self.ctx.db.transaction():
            res_id = self.create(payload, _walk_in=True)
            self.check_in(res_id, allow_dirty=allow_dirty, early_fee=data.get("early_fee"), payment=payment)
        return res_id

    def revert_check_in(self, res_id: int, reason: str) -> None:
        """Undo a check-in made by mistake (same day only)."""
        self.ctx.require("reservations.edit", "billing.void")
        res = self.get(res_id)
        if res.status != RS.CHECKED_IN:
            raise ConflictError("Only in-house reservations can have their check-in undone.")
        if not res.actual_check_in or res.actual_check_in.date() != self.ctx.clock.today():
            raise ConflictError("A check-in can only be undone on the same day.")
        reason = v.required(reason, "Reason", "reason", max_len=200)
        with self.ctx.db.transaction():
            for charge in self.ctx.repo_folio.charges(res.id, include_void=False):
                if charge.parent_id is None:
                    self.ctx.billing._void_tree(charge.id, f"Check-in undone: {reason}")
            self.repo.update(res.id, {"status": RS.CONFIRMED, "actual_check_in": None, "checked_in_by": None,
                                      "updated_at": self.ctx.now_str()})
            self.ctx.audit.log("reservations.undo_check_in", "reservation", res.id,
                               f"Undid check-in of {res.confirmation_no}: {reason}")
        self.ctx.events.emit("reservations", "rooms", "billing")

    # -- check-out -------------------------------------------------------------------------
    def check_out_preview(self, res_id: int) -> CheckOutPreview:
        res = self.get(res_id)
        folio = self.ctx.billing.folio(res_id)
        now = self.ctx.clock.now()
        today = now.date()
        p = CheckOutPreview(reservation=res, folio=folio)
        balance = folio.balance
        if res.check_out_date > today:
            new_co = max(today, res.check_in_date + timedelta(days=1))
            if new_co < res.check_out_date:
                p.early_departure, p.new_check_out = True, new_co
                p.nights_removed = nights_between(new_co, res.check_out_date)
                p.removed_value = self.ctx.billing.room_nights_value_from(res_id, new_co)
                balance -= p.removed_value
        elif res.check_out_date < today:
            p.extra_nights = nights_between(res.check_out_date, today)
            p.new_check_out = today
            p.extra_value = self.ctx.billing.nights_value(p.extra_nights, res.nightly_rate, res.discount_bp)
            balance += p.extra_value
        elif self.is_overdue(res):
            p.late = True
            item = self.ctx.repo_folio.charge_item_by_code("LATE_CHECKOUT")
            p.late_fee_default = item.default_amount if item else 0
        p.estimated_balance = balance
        return p

    def check_out(self, res_id: int, *, late_fee: Any = None, early_departure_fee: Any = None,
                  post_extra_nights: bool = True, allow_balance: bool = False,
                  payment: dict[str, Any] | None = None) -> str:
        """Check a guest out. Returns the invoice number."""
        self.ctx.require("reservations.checkout")
        res = self.get(res_id)
        if res.status != RS.CHECKED_IN:
            raise ConflictError("Only in-house guests can be checked out.")
        today = self.ctx.clock.today()
        room = self.ctx.rooms.get(res.room_id)
        late_cents = parse_amount(late_fee, field="late_fee", label="Late check-out fee") \
            if late_fee not in (None, "") else 0
        early_cents = parse_amount(early_departure_fee, field="early_fee", label="Early departure fee") \
            if early_departure_fee not in (None, "") else 0
        with self.ctx.db.transaction():
            if res.check_out_date > today:
                new_co = max(today, res.check_in_date + timedelta(days=1))
                if new_co < res.check_out_date:
                    self.repo.update(res.id, {"check_out_date": new_co.isoformat()})
                    self.ctx.billing._sync_room_nights(res.id, "Early departure")
                    if early_cents:
                        self.ctx.billing._post_system_fee(res, "EARLY_DEPARTURE", early_cents)
            elif res.check_out_date < today and post_extra_nights:
                conflicts = self.repo.conflicts(room.id, res.check_out_date, today, res.id)
                if conflicts:
                    raise ConflictError(
                        f"Extra nights cannot be posted: room {room.number} is booked by "
                        f"{conflicts[0].guest_name} ({conflicts[0].confirmation_no}). "
                        "Check out without posting extra nights and add a manual charge instead.")
                self.repo.update(res.id, {"check_out_date": today.isoformat()})
                self.ctx.billing._sync_room_nights(res.id, "Extended stay")
            if late_cents:
                self.ctx.billing._post_system_fee(res, "LATE_CHECKOUT", late_cents)
            if payment and payment.get("amount") not in (None, "", 0, "0"):
                self.ctx.billing.record_payment(res.id, amount=payment["amount"], method_id=payment.get("method_id"),
                                                reference=payment.get("reference", ""))
            balance = self.ctx.billing.balance(res.id)
            if balance > 0:
                if not allow_balance:
                    raise ConflictError(f"The guest still owes {self.ctx.settings.money(balance)}. Take a payment "
                                        "before check-out, or check out with an open balance (manager).")
                self.ctx.require("billing.checkout_balance")
            self.repo.update(res.id, {"status": RS.CHECKED_OUT, "actual_check_out": self.ctx.now_str(),
                                      "checked_out_by": self.ctx.user_id, "updated_at": self.ctx.now_str()})
            invoice_no = self.ctx.billing.issue_invoice(res.id)
            self.ctx.housekeeping._ensure_dirty_with_task(room, f"Check-out {res.confirmation_no}",
                                                          task_type="checkout")
            self.ctx.audit.log("reservations.check_out", "reservation", res.id,
                               f"Checked out {res.guest_name} from room {room.number} ({res.confirmation_no}), "
                               f"invoice {invoice_no}"
                               + (f", open balance {self.ctx.settings.money(balance)}" if balance > 0 else ""))
        self.ctx.events.emit("reservations", "rooms", "billing", "housekeeping")
        return invoice_no

    # -- room transfer ---------------------------------------------------------------------
    def transfer(self, res_id: int, new_room_id: int, reason: str, *, use_new_rate: bool = False,
                 allow_dirty: bool = False) -> None:
        self.ctx.require("reservations.transfer")
        res = self.get(res_id)
        if res.status not in (RS.CONFIRMED, RS.CHECKED_IN):
            raise ConflictError("Only upcoming or in-house reservations can change rooms.")
        new_room = self.ctx.rooms.get(int(new_room_id))
        old_room = self.ctx.rooms.get(res.room_id)
        if new_room.id == old_room.id:
            raise ValidationError("Choose a different room.", field="room_id")
        reason = v.required(reason, "Reason", "reason", max_len=200)
        today = self.ctx.clock.today()
        start = max(today, res.check_in_date)
        if not new_room.is_active or new_room.service_status != ServiceStatus.IN_SERVICE:
            raise ConflictError(f"Room {new_room.number} is not available (out of service).")
        if res.guests_count > new_room.capacity:
            raise ValidationError(f"Room {new_room.number} sleeps at most {new_room.capacity} guests.",
                                  field="room_id")
        conflicts = self.repo.conflicts(new_room.id, start, res.check_out_date, res.id)
        if conflicts:
            c = conflicts[0]
            raise ConflictError(f"Room {new_room.number} is booked by {c.guest_name} ({c.confirmation_no}) "
                                f"from {_fmt_date(c.check_in_date)}.")
        if res.status == RS.CHECKED_IN:
            occupant = self.repo.in_house_for_room(new_room.id)
            if occupant:
                raise ConflictError(f"Room {new_room.number} is occupied by {occupant.guest_name}.")
            if new_room.hk_status in (HKStatus.DIRTY, HKStatus.CLEANING) and not allow_dirty:
                raise ConflictError(f"Room {new_room.number} has not been cleaned yet.")
        new_rate = new_room.effective_rate if use_new_rate else res.nightly_rate
        with self.ctx.db.transaction():
            values: dict[str, Any] = {"room_id": new_room.id, "room_type_id": new_room.room_type_id,
                                      "updated_at": self.ctx.now_str()}
            if new_rate != res.nightly_rate:
                values["nightly_rate"] = new_rate
                values["rate_overridden"] = 0
            if res.status == RS.CHECKED_IN:
                self.ctx.billing._void_nights_from(res.id, today, f"Moved to room {new_room.number}")
            self.repo.update(res.id, values)
            if res.status == RS.CHECKED_IN:
                self.ctx.billing._sync_room_nights(res.id, "Room transfer")
                self.ctx.housekeeping._ensure_dirty_with_task(old_room, f"Guest moved to {new_room.number}",
                                                              task_type="checkout")
            self.repo.add_room_move(res.id, old_room.id, new_room.id, self.ctx.now_str(), self.ctx.user_id, reason)
            self.ctx.audit.log("reservations.transfer", "reservation", res.id,
                               f"Moved {res.guest_name} ({res.confirmation_no}) from room {old_room.number} to "
                               f"{new_room.number}: {reason}"
                               + (f"; new rate {self.ctx.settings.money(new_rate)}"
                                  if new_rate != res.nightly_rate else ""))
        self.ctx.events.emit("reservations", "rooms", "billing", "housekeeping")
