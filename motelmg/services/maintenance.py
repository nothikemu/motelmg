"""Maintenance tickets. A ticket can block its room (taking it out of
inventory) until it is resolved."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from motelmg.core import validation as v
from motelmg.core.enums import Priority, ServiceStatus, TicketCategory, TicketStatus, TaskType
from motelmg.core.errors import ConflictError, NotFoundError, ValidationError
from motelmg.core.money import parse_amount
from motelmg.models import MaintenanceTicket


class MaintenanceService:
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def repo(self):
        return self.ctx.repo_maint

    def search(self, *, statuses: Iterable[str] | None = None, room_id: int | None = None, category: str = "",
               priority: int | None = None, text: str = "", start: date | None = None,
               end: date | None = None) -> list[MaintenanceTicket]:
        self.ctx.require("maintenance.view")
        return self.repo.search(statuses=statuses, room_id=room_id, category=category, priority=priority, text=text,
                                start=start, end=end)

    def get(self, ticket_id: int) -> MaintenanceTicket:
        ticket = self.repo.get(ticket_id)
        if not ticket:
            raise NotFoundError("Ticket not found.")
        return ticket

    def _clean(self, data: dict[str, Any]) -> dict[str, Any]:
        errors: dict[str, str] = {}
        values: dict[str, Any] = {}
        try:
            values["title"] = v.required(data.get("title"), "Title", "title", max_len=120)
        except ValidationError as exc:
            errors.update(exc.field_errors)
        try:
            values["description"] = v.optional(data.get("description"), "Description", "description", max_len=2000)
            values["location"] = v.optional(data.get("location"), "Location", "location", max_len=100)
            values["assigned_to"] = v.optional(data.get("assigned_to"), "Assigned to", "assigned_to", max_len=100)
        except ValidationError as exc:
            errors.update(exc.field_errors)
        category = data.get("category") or "other"
        if category not in TicketCategory.LABELS:
            errors["category"] = "Select a category."
        values["category"] = category
        try:
            priority = int(data.get("priority") or Priority.NORMAL)
        except (TypeError, ValueError):
            priority = 0
        if priority not in Priority.LABELS:
            errors["priority"] = "Select a priority."
        values["priority"] = priority
        room_id = data.get("room_id")
        values["room_id"] = int(room_id) if room_id else None
        if not values["room_id"] and not values.get("location"):
            errors["location"] = "Choose a room or describe the location."
        values["blocks_room"] = int(bool(data.get("blocks_room")) and bool(values["room_id"]))
        if errors:
            raise ValidationError(field_errors=errors)
        return values

    def create(self, data: dict[str, Any]) -> tuple[int, list]:
        """Create a ticket. Returns (ticket id, conflicting reservations)."""
        self.ctx.require("maintenance.report")
        values = self._clean(data)
        conflicts: list = []
        room = self.ctx.rooms.get(values["room_id"]) if values["room_id"] else None
        if values["blocks_room"]:
            if not (self.ctx.can("maintenance.manage") or self.ctx.can("rooms.status")):
                values["blocks_room"] = 0
            elif self.ctx.repo_res.in_house_for_room(room.id):
                raise ConflictError(f"Room {room.number} is occupied, so it cannot be taken out of service now. "
                                    "Untick 'Take room out of service' or transfer the guest first.")
        now = self.ctx.now_str()
        values.update({"status": TicketStatus.OPEN, "reported_by": self.ctx.user_id, "created_at": now,
                       "updated_at": now})
        with self.ctx.db.transaction():
            ticket_id = self.repo.insert(values)
            if values["blocks_room"] and room and room.service_status == ServiceStatus.IN_SERVICE:
                self.ctx.repo_rooms.update_room(room.id, {"service_status": ServiceStatus.MAINTENANCE,
                                                          "service_reason": f"#{ticket_id} {values['title']}",
                                                          "service_until": None, "updated_at": now})
                self.ctx.repo_rooms.log_status(room.id, "service_status", room.service_status,
                                               ServiceStatus.MAINTENANCE, f"Ticket #{ticket_id}", self.ctx.user_id, now)
                conflicts = list(self.ctx.repo_rooms.future_reservations(room.id, self.ctx.clock.today()))
            where = f"room {room.number}" if room else values["location"]
            self.ctx.audit.log("maintenance.create", "maintenance", ticket_id,
                               f"Reported #{ticket_id} '{values['title']}' ({where})"
                               + (" — room blocked" if values["blocks_room"] else ""))
        self.ctx.events.emit("maintenance", "rooms")
        return ticket_id, conflicts

    def update(self, ticket_id: int, data: dict[str, Any]) -> list:
        self.ctx.require("maintenance.manage")
        ticket = self.get(ticket_id)
        if ticket.status not in TicketStatus.ACTIVE:
            raise ConflictError("Closed tickets cannot be edited.")
        values = self._clean({**data, "room_id": data.get("room_id", ticket.room_id)})
        if values["room_id"] != ticket.room_id and ticket.blocks_room:
            raise ConflictError("Unblock the current room before moving this ticket to another room.")
        conflicts: list = []
        now = self.ctx.now_str()
        room = self.ctx.rooms.get(values["room_id"]) if values["room_id"] else None
        with self.ctx.db.transaction():
            values["updated_at"] = now
            self.repo.update(ticket_id, values)
            if room and values["blocks_room"] and not ticket.blocks_room:
                if self.ctx.repo_res.in_house_for_room(room.id):
                    raise ConflictError(f"Room {room.number} is occupied and cannot be blocked now.")
                if room.service_status == ServiceStatus.IN_SERVICE:
                    self.ctx.repo_rooms.update_room(room.id, {"service_status": ServiceStatus.MAINTENANCE,
                                                              "service_reason": f"#{ticket_id} {values['title']}",
                                                              "updated_at": now})
                    self.ctx.repo_rooms.log_status(room.id, "service_status", room.service_status,
                                                   ServiceStatus.MAINTENANCE, f"Ticket #{ticket_id}",
                                                   self.ctx.user_id, now)
                conflicts = list(self.ctx.repo_rooms.future_reservations(room.id, self.ctx.clock.today()))
            elif room and ticket.blocks_room and not values["blocks_room"]:
                self._release_room(room.id, ticket_id)
            self.ctx.audit.log("maintenance.update", "maintenance", ticket_id, f"Updated ticket #{ticket_id}")
        self.ctx.events.emit("maintenance", "rooms")
        return conflicts

    def set_status(self, ticket_id: int, status: str, note: str = "") -> None:
        self.ctx.require("maintenance.manage")
        if status not in (TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.ON_HOLD):
            raise ValidationError("Use Resolve or Cancel to close a ticket.")
        ticket = self.get(ticket_id)
        if ticket.status not in TicketStatus.ACTIVE:
            raise ConflictError("This ticket is already closed.")
        with self.ctx.db.transaction():
            values: dict[str, Any] = {"status": status, "updated_at": self.ctx.now_str()}
            if note:
                values["description"] = (ticket.description + "\n" if ticket.description else "") + \
                    f"[{self.ctx.clock.now():%Y-%m-%d %H:%M}] {v.optional(note, 'Note', 'note', max_len=500)}"
            self.repo.update(ticket_id, values)
            self.ctx.audit.log("maintenance.status", "maintenance", ticket_id,
                               f"Ticket #{ticket_id} → {TicketStatus.LABELS[status]}")
        self.ctx.events.emit("maintenance")

    def resolve(self, ticket_id: int, resolution: str, cost: Any = None, *, cancelled: bool = False) -> None:
        self.ctx.require("maintenance.manage")
        ticket = self.get(ticket_id)
        if ticket.status not in TicketStatus.ACTIVE:
            raise ConflictError("This ticket is already closed.")
        resolution = v.required(resolution, "Resolution" if not cancelled else "Reason", "resolution", max_len=1000)
        cost_cents = parse_amount(cost, field="cost", label="Cost") if cost not in (None, "") else 0
        status = TicketStatus.CANCELLED if cancelled else TicketStatus.RESOLVED
        now = self.ctx.now_str()
        with self.ctx.db.transaction():
            self.repo.update(ticket_id, {"status": status, "resolution": resolution, "cost": cost_cents,
                                         "resolved_at": now, "resolved_by": self.ctx.user_id, "updated_at": now})
            if ticket.room_id and ticket.blocks_room:
                self._release_room(ticket.room_id, ticket_id)
            self.ctx.audit.log("maintenance.cancel" if cancelled else "maintenance.resolve", "maintenance", ticket_id,
                               f"{'Cancelled' if cancelled else 'Resolved'} #{ticket_id} '{ticket.title}': {resolution}"
                               + (f" (cost {self.ctx.settings.money(cost_cents)})" if cost_cents else ""))
        self.ctx.events.emit("maintenance", "rooms", "housekeeping")

    def _release_room(self, room_id: int, ticket_id: int) -> None:
        """Return a room to service when no other blocking tickets remain."""
        room = self.ctx.rooms.get(room_id)
        if room.service_status != ServiceStatus.MAINTENANCE:
            return
        if self.repo.active_blocking_count(room_id, exclude_id=ticket_id):
            return
        now = self.ctx.now_str()
        self.ctx.repo_rooms.update_room(room_id, {"service_status": ServiceStatus.IN_SERVICE, "service_reason": "",
                                                  "service_until": None, "updated_at": now})
        self.ctx.repo_rooms.log_status(room_id, "service_status", ServiceStatus.MAINTENANCE, ServiceStatus.IN_SERVICE,
                                       f"Ticket #{ticket_id} closed", self.ctx.user_id, now)
        room.service_status = ServiceStatus.IN_SERVICE
        self.ctx.housekeeping._ensure_dirty_with_task(room, f"After maintenance #{ticket_id}",
                                                      task_type=TaskType.TOUCH_UP)
