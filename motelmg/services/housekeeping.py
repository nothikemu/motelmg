"""Housekeeping tasks and room cleanliness status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from motelmg.core import validation as v
from motelmg.core.dates import parse_optional_date
from motelmg.core.enums import HKStatus, Priority, TaskStatus, TaskType
from motelmg.core.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from motelmg.models import HKTask, Room


@dataclass
class HKSummary:
    dirty: int = 0
    cleaning: int = 0
    clean: int = 0
    inspected: int = 0
    pending_tasks: int = 0
    in_progress_tasks: int = 0
    awaiting_inspection: int = 0
    completed_today: int = 0
    unassigned: int = 0


class HousekeepingService:
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def repo(self):
        return self.ctx.repo_hk

    def _today(self) -> date:
        return self.ctx.clock.today()

    # -- queries -----------------------------------------------------------------------
    def tasks(self, *, statuses: Iterable[str] | None = None, assigned_to: int | None = None,
              room_id: int | None = None, start: date | None = None, end: date | None = None,
              unassigned_only: bool = False) -> list[HKTask]:
        self.ctx.require("housekeeping.view")
        return self.repo.search(self._today(), statuses=statuses, assigned_to=assigned_to, room_id=room_id,
                                start=start, end=end, unassigned_only=unassigned_only)

    def get(self, task_id: int) -> HKTask:
        task = self.repo.get(task_id, self._today())
        if not task:
            raise NotFoundError("Task not found.")
        return task

    def summary(self) -> HKSummary:
        s = HKSummary()
        for room in self.ctx.repo_rooms.list_rooms():
            setattr(s, room.hk_status, getattr(s, room.hk_status) + 1)
        today = self._today()
        for task in self.repo.search(today, statuses=["pending", "in_progress", "completed"]):
            if task.status == TaskStatus.PENDING:
                s.pending_tasks += 1
                if task.assigned_to is None:
                    s.unassigned += 1
            elif task.status == TaskStatus.IN_PROGRESS:
                s.in_progress_tasks += 1
            elif task.status == TaskStatus.COMPLETED:
                if task.task_type in TaskType.CLEANING and task.hk_status == HKStatus.CLEAN:
                    s.awaiting_inspection += 1
                if task.completed_at and task.completed_at.date() == today:
                    s.completed_today += 1
        return s

    # -- internal helpers used by other services ------------------------------------------
    def _priority_for(self, room: Room, task_type: str) -> int:
        today = self._today()
        arrival = any(r.room_id == room.id for r in self.ctx.repo_res.arrivals_pending(today))
        if arrival and task_type in TaskType.CLEANING:
            return Priority.URGENT
        if task_type == TaskType.CHECKOUT:
            return Priority.HIGH
        return Priority.NORMAL

    def _ensure_dirty_with_task(self, room: Room, reason: str, *, task_type: str = TaskType.CHECKOUT) -> int | None:
        """Mark a room dirty and make sure a cleaning task exists (caller holds transaction)."""
        self.ctx.rooms._set_hk(room, HKStatus.DIRTY, reason)
        if self.repo.open_task(room.id, task_type):
            return None
        return self.repo.insert({
            "room_id": room.id, "task_type": task_type, "priority": self._priority_for(room, task_type),
            "status": TaskStatus.PENDING, "notes": reason, "due_date": self._today().isoformat(),
            "created_by": self.ctx.user_id, "created_at": self.ctx.now_str()})

    def _can_work(self, task: HKTask) -> None:
        session = self.ctx.session
        if session is None:
            raise PermissionDenied("You must be signed in.")
        if session.has("housekeeping.manage"):
            return
        self.ctx.require("housekeeping.work")
        if task.assigned_to and task.assigned_to != session.user_id:
            raise PermissionDenied(f"This task is assigned to {task.assigned_name}.")

    # -- task management ---------------------------------------------------------------
    def create_task(self, data: dict[str, Any]) -> int:
        self.ctx.require("housekeeping.manage")
        room = self.ctx.rooms.get(int(data.get("room_id") or 0)) if data.get("room_id") else None
        if room is None:
            raise ValidationError("Select a room.", field="room_id")
        task_type = data.get("task_type") or TaskType.CHECKOUT
        if task_type not in TaskType.LABELS:
            raise ValidationError("Select a task type.", field="task_type")
        priority = int(data.get("priority") or self._priority_for(room, task_type))
        if priority not in Priority.LABELS:
            raise ValidationError("Select a priority.", field="priority")
        assigned = self._assignee(data.get("assigned_to"))
        due = parse_optional_date(data.get("due_date"), field="due_date", label="Due date") or self._today()
        notes = v.optional(data.get("notes"), "Notes", "notes", max_len=1000)
        if self.repo.open_task(room.id, task_type):
            raise ConflictError(f"Room {room.number} already has an open {TaskType.LABELS[task_type].lower()} task.")
        with self.ctx.db.transaction():
            task_id = self.repo.insert({
                "room_id": room.id, "task_type": task_type, "priority": priority, "status": TaskStatus.PENDING,
                "assigned_to": assigned, "notes": notes, "due_date": due.isoformat(),
                "created_by": self.ctx.user_id, "created_at": self.ctx.now_str()})
            if task_type in (TaskType.CHECKOUT, TaskType.DEEP_CLEAN) and \
                    not self.ctx.repo_res.in_house_for_room(room.id):
                self.ctx.rooms._set_hk(room, HKStatus.DIRTY, f"{TaskType.LABELS[task_type]} requested")
            self.ctx.audit.log("housekeeping.create", "room", room.id,
                               f"Created {TaskType.LABELS[task_type].lower()} task for room {room.number}")
        self.ctx.events.emit("housekeeping", "rooms")
        return task_id

    def _assignee(self, user_id: Any) -> int | None:
        if user_id in (None, "", 0):
            return None
        user = self.ctx.repo_staff.get_user(int(user_id))
        if not user or not user.is_active:
            raise ValidationError("Select an active staff member.", field="assigned_to")
        return user.id

    def assign(self, task_ids: list[int], user_id: int | None) -> None:
        self.ctx.require("housekeeping.manage")
        assignee = self._assignee(user_id)
        name = self.ctx.repo_staff.get_user(assignee).full_name if assignee else "nobody"
        with self.ctx.db.transaction():
            for task_id in task_ids:
                task = self.get(task_id)
                if task.status not in TaskStatus.OPEN:
                    continue
                self.repo.update(task_id, {"assigned_to": assignee})
                self.ctx.audit.log("housekeeping.assign", "room", task.room_id,
                                   f"Assigned room {task.room_number} ({TaskType.LABELS[task.task_type].lower()}) "
                                   f"to {name}")
        self.ctx.events.emit("housekeeping")

    def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        self.ctx.require("housekeeping.manage")
        task = self.get(task_id)
        values: dict[str, Any] = {}
        if "priority" in data:
            priority = int(data["priority"])
            if priority not in Priority.LABELS:
                raise ValidationError("Select a priority.", field="priority")
            values["priority"] = priority
        if "notes" in data:
            values["notes"] = v.optional(data.get("notes"), "Notes", "notes", max_len=1000)
        if "due_date" in data:
            due = parse_optional_date(data.get("due_date"), field="due_date", label="Due date")
            values["due_date"] = (due or task.due_date).isoformat()
        if "assigned_to" in data:
            values["assigned_to"] = self._assignee(data.get("assigned_to"))
        with self.ctx.db.transaction():
            self.repo.update(task_id, values)
            self.ctx.audit.log("housekeeping.update", "room", task.room_id, f"Updated task for room {task.room_number}")
        self.ctx.events.emit("housekeeping")

    def start(self, task_id: int) -> None:
        task = self.get(task_id)
        self._can_work(task)
        if task.status != TaskStatus.PENDING:
            raise ConflictError("Only pending tasks can be started.")
        room = self.ctx.rooms.get(task.room_id)
        with self.ctx.db.transaction():
            values: dict[str, Any] = {"status": TaskStatus.IN_PROGRESS, "started_at": self.ctx.now_str()}
            if task.assigned_to is None:
                values["assigned_to"] = self.ctx.user_id
            self.repo.update(task_id, values)
            if task.task_type in TaskType.CLEANING and not self.ctx.repo_res.in_house_for_room(room.id):
                self.ctx.rooms._set_hk(room, HKStatus.CLEANING, "Cleaning started")
            self.ctx.audit.log("housekeeping.start", "room", room.id,
                               f"Started {TaskType.LABELS[task.task_type].lower()} of room {room.number}")
        self.ctx.events.emit("housekeeping", "rooms")

    def complete(self, task_id: int, notes: str = "") -> None:
        task = self.get(task_id)
        self._can_work(task)
        if task.status not in TaskStatus.OPEN:
            raise ConflictError("This task is already finished.")
        if task.task_type == TaskType.INSPECTION:
            self.ctx.require("housekeeping.inspect")
        notes = v.optional(notes, "Notes", "notes", max_len=1000)
        room = self.ctx.rooms.get(task.room_id)
        occupied = bool(self.ctx.repo_res.in_house_for_room(room.id))
        with self.ctx.db.transaction():
            values: dict[str, Any] = {"status": TaskStatus.COMPLETED, "completed_at": self.ctx.now_str(),
                                      "completed_by": self.ctx.user_id}
            if task.started_at is None:
                values["started_at"] = self.ctx.now_str()
            if task.assigned_to is None:
                values["assigned_to"] = self.ctx.user_id
            if notes:
                values["notes"] = (task.notes + "\n" if task.notes else "") + notes
            if task.task_type == TaskType.INSPECTION:
                values.update({"status": TaskStatus.INSPECTED, "inspected_at": self.ctx.now_str(),
                               "inspected_by": self.ctx.user_id})
                self.ctx.rooms._set_hk(room, HKStatus.INSPECTED, "Inspection passed")
            elif task.task_type in TaskType.CLEANING or not occupied:
                self.ctx.rooms._set_hk(room, HKStatus.CLEAN, "Cleaning completed")
            self.repo.update(task_id, values)
            self.ctx.audit.log("housekeeping.complete", "room", room.id,
                               f"Completed {TaskType.LABELS[task.task_type].lower()} of room {room.number}")
        self.ctx.events.emit("housekeeping", "rooms")

    def inspect(self, task_id: int, passed: bool, notes: str = "") -> None:
        self.ctx.require("housekeeping.inspect")
        task = self.get(task_id)
        if task.status != TaskStatus.COMPLETED:
            raise ConflictError("Only completed cleaning tasks can be inspected.")
        notes = v.optional(notes, "Notes", "notes", max_len=1000)
        if not passed and not notes:
            raise ValidationError("Describe what needs to be redone.", field="notes")
        room = self.ctx.rooms.get(task.room_id)
        occupied = bool(self.ctx.repo_res.in_house_for_room(room.id))
        with self.ctx.db.transaction():
            if passed:
                self.repo.update(task_id, {"status": TaskStatus.INSPECTED, "inspected_at": self.ctx.now_str(),
                                           "inspected_by": self.ctx.user_id, "inspection_notes": notes})
                if not occupied:
                    self.ctx.rooms._set_hk(room, HKStatus.INSPECTED, "Inspection passed")
                summary = f"Room {room.number} passed inspection"
            else:
                self.repo.update(task_id, {"status": TaskStatus.PENDING, "completed_at": None, "completed_by": None,
                                           "started_at": None, "inspection_notes": notes,
                                           "priority": min(task.priority, Priority.HIGH)})
                if not occupied:
                    self.ctx.rooms._set_hk(room, HKStatus.DIRTY, f"Failed inspection: {notes}")
                summary = f"Room {room.number} failed inspection: {notes}"
            self.ctx.audit.log("housekeeping.inspect", "room", room.id, summary)
        self.ctx.events.emit("housekeeping", "rooms")

    def cancel(self, task_id: int, reason: str = "") -> None:
        self.ctx.require("housekeeping.manage")
        task = self.get(task_id)
        if task.status not in TaskStatus.OPEN:
            raise ConflictError("Only open tasks can be cancelled.")
        with self.ctx.db.transaction():
            self.repo.update(task_id, {"status": TaskStatus.CANCELLED,
                                       "notes": (task.notes + "\n" if task.notes else "") + f"Cancelled: {reason}"})
            self.ctx.audit.log("housekeeping.cancel", "room", task.room_id,
                               f"Cancelled task for room {task.room_number}" + (f": {reason}" if reason else ""))
        self.ctx.events.emit("housekeeping")

    # -- direct room status changes ----------------------------------------------------
    def set_room_status(self, room_id: int, status: str, reason: str = "") -> None:
        if status == HKStatus.INSPECTED:
            self.ctx.require("housekeeping.inspect")
        elif not self.ctx.can("housekeeping.manage"):
            self.ctx.require("housekeeping.work")
        if status not in HKStatus.ALL:
            raise ValidationError("Invalid status.")
        room = self.ctx.rooms.get(room_id)
        reason = v.optional(reason, "Reason", "reason", max_len=300)
        with self.ctx.db.transaction():
            if status == HKStatus.DIRTY:
                self._ensure_dirty_with_task(room, reason or "Marked dirty", task_type=TaskType.TOUCH_UP
                                             if self.ctx.repo_res.in_house_for_room(room.id) else TaskType.CHECKOUT)
            else:
                self.ctx.rooms._set_hk(room, status, reason or "Status changed manually")
                if status in (HKStatus.CLEAN, HKStatus.INSPECTED):
                    for row in self.repo.open_task(room.id):
                        if row["task_type"] in TaskType.CLEANING:
                            values: dict[str, Any] = {"status": TaskStatus.COMPLETED,
                                                      "completed_at": self.ctx.now_str(),
                                                      "completed_by": self.ctx.user_id}
                            if status == HKStatus.INSPECTED:
                                values.update({"status": TaskStatus.INSPECTED, "inspected_at": self.ctx.now_str(),
                                               "inspected_by": self.ctx.user_id})
                            self.repo.update(row["id"], values)
            self.ctx.audit.log("housekeeping.room_status", "room", room.id,
                               f"Room {room.number} marked {HKStatus.LABELS[status].lower()}"
                               + (f" ({reason})" if reason else ""))
        self.ctx.events.emit("housekeeping", "rooms")

    def generate_daily_tasks(self) -> int:
        """Create stayover tasks for occupied rooms and cleaning tasks for dirty
        vacant rooms that have none. Returns the number of tasks created."""
        self.ctx.require("housekeeping.manage")
        today = self._today()
        created = 0
        in_house = {r.room_id: r for r in self.ctx.repo_res.in_house()}
        with self.ctx.db.transaction():
            for room in self.ctx.repo_rooms.list_rooms():
                res = in_house.get(room.id)
                if res is not None:
                    if res.check_out_date <= today or res.check_in_date == today:
                        continue
                    if self.repo.open_task(room.id, TaskType.STAYOVER):
                        continue
                    self.repo.insert({"room_id": room.id, "task_type": TaskType.STAYOVER,
                                      "priority": Priority.NORMAL, "status": TaskStatus.PENDING,
                                      "notes": f"Stayover - {res.guest_name}", "due_date": today.isoformat(),
                                      "created_by": self.ctx.user_id, "created_at": self.ctx.now_str()})
                    created += 1
                elif room.hk_status in (HKStatus.DIRTY,) and not self.repo.open_task(room.id):
                    self.repo.insert({"room_id": room.id, "task_type": TaskType.CHECKOUT,
                                      "priority": self._priority_for(room, TaskType.CHECKOUT),
                                      "status": TaskStatus.PENDING, "notes": "Room is dirty",
                                      "due_date": today.isoformat(), "created_by": self.ctx.user_id,
                                      "created_at": self.ctx.now_str()})
                    created += 1
            if created:
                self.ctx.audit.log("housekeeping.generate", "housekeeping", None,
                                   f"Generated {created} housekeeping task(s) for {today.isoformat()}")
        self.ctx.events.emit("housekeeping")
        return created

    def staff(self):
        return self.ctx.users.housekeepers()
