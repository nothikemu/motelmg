"""Room inventory, room types/rates, availability and room status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from motelmg.core import validation as v
from motelmg.core.dates import parse_optional_date
from motelmg.core.enums import HKStatus, RoomState, ServiceStatus
from motelmg.core.errors import ConflictError, NotFoundError, ValidationError
from motelmg.core.money import parse_amount
from motelmg.models import Reservation, Room, RoomType


@dataclass
class RoomBoardItem:
    room: Room
    state: str
    in_house: Reservation | None = None
    arrival: Reservation | None = None
    next_reservation: Reservation | None = None
    open_tickets: int = 0
    open_task_type: str = ""
    open_task_status: str = ""
    open_task_assignee: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.state == RoomState.AVAILABLE


def departure_overdue(res: Reservation, now: datetime, check_out_time, grace_minutes: int) -> bool:
    """True when an in-house guest is past their departure time."""
    if res.status != "checked_in":
        return False
    today = now.date()
    if res.check_out_date < today:
        return True
    if res.check_out_date > today:
        return False
    limit = check_out_time
    if res.late_checkout_until:
        try:
            limit = datetime.strptime(res.late_checkout_until, "%H:%M").time()
        except ValueError:
            pass
    deadline = datetime.combine(today, limit) + timedelta(minutes=grace_minutes)
    return now > deadline


class RoomService:
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def repo(self):
        return self.ctx.repo_rooms

    # -- room types ----------------------------------------------------------------
    def list_types(self, include_inactive: bool = False) -> list[RoomType]:
        return self.repo.list_types(include_inactive)

    def get_type(self, type_id: int) -> RoomType:
        room_type = self.repo.get_type(type_id)
        if not room_type:
            raise NotFoundError("Room type not found.")
        return room_type

    def save_type(self, type_id: int | None, data: dict[str, Any], *, require_permission: bool = True) -> int:
        if require_permission:
            self.ctx.require("rooms.manage")
        errors: dict[str, str] = {}
        values: dict[str, Any] = {}
        for key, label, max_len, req in (("name", "Name", 60, True), ("code", "Code", 12, True),
                                         ("beds", "Beds", 60, False), ("description", "Description", 500, False)):
            try:
                values[key] = (v.required if req else v.optional)(data.get(key), label, key, max_len=max_len)
            except ValidationError as exc:
                errors.update(exc.field_errors)
        if values.get("code") and not v.CODE_RE.match(values["code"]):
            errors["code"] = "Code may contain letters, numbers, dash and underscore only."
        try:
            values["base_rate"] = parse_amount(data.get("base_rate"), field="base_rate", label="Nightly rate",
                                               allow_zero=False)
        except ValidationError as exc:
            errors.update(exc.field_errors)
        try:
            values["max_occupancy"] = v.int_range(data.get("max_occupancy", 2), "Max occupancy", "max_occupancy",
                                                  1, 20)
        except ValidationError as exc:
            errors.update(exc.field_errors)
        if errors:
            raise ValidationError(field_errors=errors)
        values["code"] = values["code"].upper()
        values["is_active"] = int(bool(data.get("is_active", True)))
        values["sort_order"] = int(data.get("sort_order") or 0)
        now = self.ctx.now_str()
        values["updated_at"] = now
        with self.ctx.db.transaction():
            if type_id:
                old = self.get_type(type_id)
                if not values["is_active"] and old.room_count:
                    raise ConflictError("Rooms are still assigned to this type. Move them to another type first.")
                self.repo.update_type(type_id, values)
                changes = {"base_rate": (old.base_rate, values["base_rate"])} \
                    if old.base_rate != values["base_rate"] else {}
                self.ctx.audit.log("rooms.type_update", "room_type", type_id,
                                   f"Updated room type '{values['name']}'", changes or None)
            else:
                values["created_at"] = now
                type_id = self.repo.insert_type(values)
                self.ctx.audit.log("rooms.type_create", "room_type", type_id,
                                   f"Created room type '{values['name']}'")
        self.ctx.events.emit("rooms")
        return type_id

    def delete_type(self, type_id: int) -> None:
        self.ctx.require("rooms.manage")
        room_type = self.get_type(type_id)
        if self.repo.type_in_use(type_id):
            raise ConflictError("This room type has rooms or reservations. Deactivate it instead of deleting.")
        with self.ctx.db.transaction():
            self.repo.delete_type(type_id)
            self.ctx.audit.log("rooms.type_delete", "room_type", type_id, f"Deleted room type '{room_type.name}'")
        self.ctx.events.emit("rooms")

    # -- rooms -----------------------------------------------------------------------
    def list_rooms(self, include_inactive: bool = False) -> list[Room]:
        return self.repo.list_rooms(include_inactive)

    def get(self, room_id: int) -> Room:
        room = self.repo.get_room(room_id)
        if not room:
            raise NotFoundError("Room not found.")
        return room

    def save_room(self, room_id: int | None, data: dict[str, Any], *, require_permission: bool = True) -> int:
        if require_permission:
            self.ctx.require("rooms.manage")
        errors: dict[str, str] = {}
        number = v.clean(data.get("number")).upper()
        if not number:
            errors["number"] = "Room number is required."
        elif not v.ROOM_NUMBER_RE.match(number):
            errors["number"] = "Use up to 10 letters, digits or dashes (e.g. 101, 2B, A-12)."
        type_id = data.get("room_type_id")
        room_type = self.repo.get_type(int(type_id)) if type_id else None
        if room_type is None:
            errors["room_type_id"] = "Select a room type."
        values: dict[str, Any] = {"number": number, "room_type_id": room_type.id if room_type else None}
        try:
            values["floor"] = v.optional(data.get("floor"), "Floor", "floor", max_len=20)
            values["beds"] = v.optional(data.get("beds"), "Beds", "beds", max_len=60)
            values["description"] = v.optional(data.get("description"), "Description", "description", max_len=500)
            values["features"] = v.optional(data.get("features"), "Features", "features", max_len=300)
        except ValidationError as exc:
            errors.update(exc.field_errors)
        rate = data.get("rate")
        if rate in (None, ""):
            values["rate"] = None
        else:
            try:
                values["rate"] = parse_amount(rate, field="rate", label="Room rate", allow_zero=False)
            except ValidationError as exc:
                errors.update(exc.field_errors)
        occ = data.get("max_occupancy")
        if occ in (None, "", 0):
            values["max_occupancy"] = None
        else:
            try:
                values["max_occupancy"] = v.int_range(occ, "Max occupancy", "max_occupancy", 1, 20)
            except ValidationError as exc:
                errors.update(exc.field_errors)
        if errors:
            raise ValidationError(field_errors=errors)
        existing = self.repo.get_by_number(number)
        if existing and existing.id != room_id:
            raise ValidationError("A room with this number already exists.", field="number")
        values["sort_order"] = int(data.get("sort_order") or 0)
        values["is_active"] = int(bool(data.get("is_active", True)))
        now = self.ctx.now_str()
        values["updated_at"] = now
        with self.ctx.db.transaction():
            if room_id:
                old = self.get(room_id)
                if not values["is_active"] and old.is_active:
                    self._ensure_can_deactivate(room_id)
                self.repo.update_room(room_id, values)
                self.ctx.audit.log("rooms.update", "room", room_id, f"Updated room {number}")
            else:
                values["created_at"] = now
                values["hk_status"] = data.get("hk_status", HKStatus.CLEAN)
                room_id = self.repo.insert_room(values)
                self.ctx.audit.log("rooms.create", "room", room_id, f"Created room {number}")
        self.ctx.events.emit("rooms")
        return room_id

    def _ensure_can_deactivate(self, room_id: int) -> None:
        if self.ctx.repo_res.in_house_for_room(room_id):
            raise ConflictError("A guest is checked in to this room.")
        upcoming = self.repo.future_reservations(room_id, self.ctx.clock.today())
        if upcoming:
            raise ConflictError(f"This room has {len(upcoming)} upcoming reservation(s). Move them first.")

    def delete_room(self, room_id: int) -> str:
        """Delete a room, or deactivate it when it has history. Returns 'deleted' or 'deactivated'."""
        self.ctx.require("rooms.manage")
        room = self.get(room_id)
        self._ensure_can_deactivate(room_id)
        with self.ctx.db.transaction():
            if self.repo.room_has_history(room_id):
                self.repo.update_room(room_id, {"is_active": 0, "updated_at": self.ctx.now_str()})
                self.ctx.audit.log("rooms.deactivate", "room", room_id, f"Archived room {room.number}")
                result = "deactivated"
            else:
                self.repo.delete_room(room_id)
                self.ctx.audit.log("rooms.delete", "room", room_id, f"Deleted room {room.number}")
                result = "deleted"
        self.ctx.events.emit("rooms")
        return result

    def bulk_create(self, numbers: list[str], room_type_id: int, floor: str = "") -> list[int]:
        self.ctx.require("rooms.manage")
        ids = []
        with self.ctx.db.transaction():
            for number in numbers:
                ids.append(self.save_room(None, {"number": number, "room_type_id": room_type_id, "floor": floor}))
        return ids

    # -- availability --------------------------------------------------------------
    def sellable_for(self, room: Room, check_in: date) -> bool:
        """Can the room be sold for a stay starting ``check_in``?"""
        if not room.is_active:
            return False
        if room.service_status == ServiceStatus.IN_SERVICE:
            return True
        # Out of service with a known return date before the arrival is fine.
        return room.service_until is not None and room.service_until <= check_in \
            and check_in > self.ctx.clock.today()

    def available_rooms(self, check_in: date, check_out: date, *, room_type_id: int | None = None,
                        exclude_reservation: int | None = None, guests: int | None = None) -> list[Room]:
        booked = self.repo.booked_room_ids(check_in, check_out, exclude_reservation)
        rooms = []
        for room in self.repo.list_rooms():
            if room.id in booked or not self.sellable_for(room, check_in):
                continue
            if room_type_id and room.room_type_id != room_type_id:
                continue
            if guests and guests > room.capacity:
                continue
            rooms.append(room)
        return rooms

    def availability_by_type(self, check_in: date, check_out: date) -> dict[int, int]:
        counts: dict[int, int] = {}
        for room in self.available_rooms(check_in, check_out):
            counts[room.room_type_id] = counts.get(room.room_type_id, 0) + 1
        return counts

    # -- board -----------------------------------------------------------------------
    def board(self, day: date | None = None) -> list[RoomBoardItem]:
        now = self.ctx.clock.now()
        today = day or now.date()
        settings = self.ctx.settings
        co_time = settings.check_out_time()
        grace = settings.get_int("policy.late_checkout_grace_minutes")
        in_house = {r.room_id: r for r in self.ctx.repo_res.in_house()}
        arrivals: dict[int, Reservation] = {}
        for res in self.ctx.repo_res.arrivals_pending(today):
            arrivals.setdefault(res.room_id, res)
        upcoming: dict[int, Reservation] = {}
        for res in self.ctx.repo_res.search(statuses=["confirmed"], arrival_from=today + timedelta(days=1),
                                             arrival_to=today + timedelta(days=30),
                                             order="r.check_in_date ASC"):
            upcoming.setdefault(res.room_id, res)
        tickets = self.ctx.repo_maint.open_count_by_room()
        open_tasks: dict[int, Any] = {}
        for task in self.ctx.repo_hk.search(today, statuses=["pending", "in_progress"]):
            open_tasks.setdefault(task.room_id, task)
        items = []
        for room in self.repo.list_rooms():
            res_in = in_house.get(room.id)
            arrival = arrivals.get(room.id)
            flags: list[str] = []
            if room.service_status == ServiceStatus.OUT_OF_SERVICE:
                state = RoomState.OUT_OF_SERVICE
            elif room.service_status == ServiceStatus.MAINTENANCE:
                state = RoomState.MAINTENANCE
            elif res_in:
                if departure_overdue(res_in, now, co_time, grace):
                    state = RoomState.OVERDUE
                elif res_in.check_out_date <= today:
                    state = RoomState.DUE_OUT
                else:
                    state = RoomState.OCCUPIED
            elif arrival:
                state = RoomState.RESERVED
            elif room.hk_status in (HKStatus.CLEAN, HKStatus.INSPECTED):
                state = RoomState.AVAILABLE
                if settings.get_bool("policy.require_inspection") and room.hk_status != HKStatus.INSPECTED:
                    state = RoomState.VACANT_DIRTY
            else:
                state = RoomState.VACANT_DIRTY
            if room.service_status != ServiceStatus.IN_SERVICE and (res_in or arrival):
                flags.append("conflict")
            if arrival and room.hk_status in (HKStatus.DIRTY, HKStatus.CLEANING):
                flags.append("arrival_dirty")
            if res_in and arrival:
                flags.append("arrival_blocked")
            task = open_tasks.get(room.id)
            items.append(RoomBoardItem(
                room=room, state=state, in_house=res_in, arrival=arrival,
                next_reservation=upcoming.get(room.id), open_tickets=tickets.get(room.id, 0),
                open_task_type=task.task_type if task else "", open_task_status=task.status if task else "",
                open_task_assignee=task.assigned_name if task else "", flags=flags))
        return items

    # -- status changes -------------------------------------------------------------
    def _set_hk(self, room: Room, status: str, reason: str = "") -> None:
        """Internal: change housekeeping status and log it (caller holds transaction)."""
        if status not in HKStatus.ALL:
            raise ValidationError("Invalid housekeeping status.")
        if room.hk_status == status:
            return
        self.repo.update_room(room.id, {"hk_status": status, "updated_at": self.ctx.now_str()})
        self.repo.log_status(room.id, "hk_status", room.hk_status, status, reason, self.ctx.user_id,
                             self.ctx.now_str())
        room.hk_status = status

    def set_service_status(self, room_id: int, status: str, reason: str, until: Any = None) -> list:
        """Put a room out of service / under maintenance, or back in service.

        Returns the list of upcoming reservations that conflict with the
        closure so the caller can warn the user and reassign them.
        """
        self.ctx.require("rooms.status")
        room = self.get(room_id)
        if status not in ServiceStatus.ALL:
            raise ValidationError("Invalid room status.")
        reason = v.optional(reason, "Reason", "reason", max_len=300)
        until_date = parse_optional_date(until, field="until", label="Expected return date")
        today = self.ctx.clock.today()
        if status != ServiceStatus.IN_SERVICE:
            if not reason:
                raise ValidationError("Please give a reason.", field="reason")
            if until_date and until_date < today:
                raise ValidationError("Expected return date cannot be in the past.", field="until")
            if self.ctx.repo_res.in_house_for_room(room_id):
                raise ConflictError(f"Room {room.number} is occupied. Transfer the guest to another room "
                                    "before taking it out of service.")
        with self.ctx.db.transaction():
            old = room.service_status
            values: dict[str, Any] = {"service_status": status, "updated_at": self.ctx.now_str()}
            if status == ServiceStatus.IN_SERVICE:
                values.update({"service_reason": "", "service_until": None})
            else:
                values.update({"service_reason": reason, "service_until": until_date.isoformat() if until_date
                               else None})
            self.repo.update_room(room_id, values)
            self.repo.log_status(room_id, "service_status", old, status, reason, self.ctx.user_id,
                                 self.ctx.now_str())
            if status == ServiceStatus.IN_SERVICE and old != ServiceStatus.IN_SERVICE:
                # A room coming back from maintenance must be cleaned before it is sold.
                room.service_status = status
                self.ctx.housekeeping._ensure_dirty_with_task(room, "Returned to service", task_type="touch_up")
            label = ServiceStatus.LABELS[status]
            self.ctx.audit.log("rooms.service_status", "room", room_id,
                               f"Room {room.number}: {ServiceStatus.LABELS.get(old, old)} → {label}"
                               + (f" ({reason})" if reason else ""))
        self.ctx.events.emit("rooms", "housekeeping")
        if status == ServiceStatus.IN_SERVICE:
            return []
        return list(self.repo.future_reservations(room_id, today, until_date))

    def status_history(self, room_id: int):
        return self.repo.status_history(room_id)

    def conflicting_reservations(self) -> list[tuple[Room, Any]]:
        """Upcoming reservations assigned to rooms that will not be sellable."""
        today = self.ctx.clock.today()
        result = []
        for room in self.repo.list_rooms(include_inactive=True):
            if room.service_status == ServiceStatus.IN_SERVICE and room.is_active:
                continue
            for row in self.repo.future_reservations(room.id, today):
                arrival = date.fromisoformat(row["check_in_date"])
                if not room.is_active or room.service_until is None or room.service_until > arrival:
                    result.append((room, row))
        return result
