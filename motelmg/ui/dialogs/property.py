"""Rooms, room types, service status, maintenance tickets and housekeeping tasks."""

from __future__ import annotations

from datetime import timedelta

from PySide6.QtWidgets import QCheckBox, QRadioButton, QVBoxLayout

from motelmg.core.enums import Priority, ServiceStatus, TaskType, TicketCategory
from motelmg.ui.widgets.common import Banner, label
from motelmg.ui.widgets.dialogs import BaseDialog
from motelmg.ui.widgets.forms import (FormGrid, MoneyEdit, OptionalDateEdit, combo, line, spin, text_area)


class RoomTypeDialog(BaseDialog):
    def __init__(self, parent, app, type_id: int | None = None):
        self.app, self.ctx, self.type_id = app, app.ctx, type_id
        rt = self.ctx.rooms.get_type(type_id) if type_id else None
        super().__init__(parent, f"Edit {rt.name}" if rt else "New room type",
                         "Room types group rooms that share a standard rate and capacity.", icon_name="layers",
                         width=560)
        self.form = self.register_form(FormGrid(2))
        self.form.add("name", "Name", line(rt.name if rt else "", "e.g. Standard Queen", 60), required=True)
        self.form.add("code", "Short code", line(rt.code if rt else "", "e.g. SQ", 12), required=True)
        rate = MoneyEdit(rt.base_rate if rt else None)
        self.form.add("base_rate", "Nightly rate", rate, required=True)
        self.form.add("max_occupancy", "Max guests", spin(rt.max_occupancy if rt else 2, 1, 20))
        self.form.add("beds", "Beds", line(rt.beds if rt else "", "e.g. 1 Queen", 60))
        self.form.add("sort_order", "Display order", spin(rt.sort_order if rt else 0, 0, 999))
        self.form.add("description", "Description", text_area(rt.description if rt else "",
                                                               "Shown on quotes and to staff", 60), span=2)
        active = QCheckBox("Active (available for new bookings)")
        active.setChecked(rt.is_active if rt else True)
        self.form.add("is_active", "", active)
        self.body.addWidget(self.form)
        if rt:
            self.body.addWidget(label(f"{rt.room_count} room(s) use this type. Changing the rate does not affect "
                                      "existing reservations.", "faint", wrap=True))
        self.add_cancel()
        self.add_footer_button("Save", self._save, "primary", default=True)

    def _save(self) -> None:
        if self.attempt(lambda: self.ctx.rooms.save_type(self.type_id, self.form.values())):
            self.app.toast("Room type saved")


class RoomDialog(BaseDialog):
    def __init__(self, parent, app, room_id: int | None = None):
        self.app, self.ctx, self.room_id = app, app.ctx, room_id
        room = self.ctx.rooms.get(room_id) if room_id else None
        super().__init__(parent, f"Edit room {room.number}" if room else "New room",
                         "Rooms inherit the rate, beds and capacity of their type unless you override them.",
                         icon_name="bed", width=580)
        types = self.ctx.rooms.list_types()
        self.form = self.register_form(FormGrid(2))
        self.form.add("number", "Room number", line(room.number if room else "", "e.g. 101", 10), required=True)
        self.form.add("room_type_id", "Room type", combo([(f"{t.name} ({app.fmt.money(t.base_rate)})", t.id)
                                                          for t in types], room.room_type_id if room else None),
                      required=True)
        self.form.add("floor", "Floor / building", line(room.floor if room else "", "e.g. 1", 20))
        self.form.add("sort_order", "Display order", spin(room.sort_order if room else 0, 0, 999))
        rate = MoneyEdit(room.rate if room else None, placeholder="Use type rate")
        self.form.add("rate", "Rate override", rate, hint="Leave empty to use the room type rate")
        occ = spin(room.max_occupancy or 0 if room else 0, 0, 20)
        occ.setSpecialValueText("Type default")
        self.form.add("max_occupancy", "Max guests override", occ)
        self.form.add("beds", "Beds override", line(room.beds if room else "", "e.g. 1 King + sofa", 60), span=2)
        self.form.add("features", "Features", line(room.features if room else "",
                                                   "Comma separated: accessible, kitchenette, pet friendly", 300),
                      span=2)
        self.form.add("description", "Description", text_area(room.description if room else "", "", 54), span=2)
        active = QCheckBox("Active (part of the inventory)")
        active.setChecked(room.is_active if room else True)
        self.form.add("is_active", "", active)
        self.body.addWidget(self.form)
        self.add_cancel()
        self.add_footer_button("Save room", self._save, "primary", default=True)

    def _save(self) -> None:
        values = self.form.values()
        if values["max_occupancy"] == 0:
            values["max_occupancy"] = None
        if self.attempt(lambda: self.ctx.rooms.save_room(self.room_id, values)):
            self.app.toast(f"Room {values['number'].upper()} saved")


class BulkRoomsDialog(BaseDialog):
    def __init__(self, parent, app):
        self.app, self.ctx = app, app.ctx
        super().__init__(parent, "Add several rooms", "Create a run of numbered rooms of the same type.",
                         icon_name="grid", width=520)
        types = self.ctx.rooms.list_types()
        self.form = self.register_form(FormGrid(2))
        self.first = spin(101, 1, 99999)
        self.count = spin(5, 1, 200)
        self.form.add("first", "First number", self.first)
        self.form.add("count", "How many", self.count)
        self.form.add("room_type_id", "Room type", combo([(t.name, t.id) for t in types]), required=True)
        self.form.add("floor", "Floor", line("", "e.g. 1", 20))
        self.preview = label("", "faint", wrap=True)
        self.body.addWidget(self.form)
        self.body.addWidget(self.preview)
        self.first.valueChanged.connect(self._update)
        self.count.valueChanged.connect(self._update)
        self._update()
        self.add_cancel()
        self.add_footer_button("Create rooms", self._save, "primary", default=True)

    def _numbers(self) -> list[str]:
        return [str(self.first.value() + i) for i in range(self.count.value())]

    def _update(self) -> None:
        nums = self._numbers()
        self.preview.setText(f"Rooms {nums[0]} – {nums[-1]} will be created." if len(nums) > 1
                             else f"Room {nums[0]} will be created.")

    def _save(self) -> None:
        values = self.form.values()
        if self.attempt(lambda: self.ctx.rooms.bulk_create(self._numbers(), values["room_type_id"],
                                                           values["floor"])):
            self.app.toast(f"{len(self._numbers())} rooms created")


class ServiceStatusDialog(BaseDialog):
    """Take a room out of service / under maintenance."""

    def __init__(self, parent, app, room_id: int):
        self.app, self.ctx, self.room_id = app, app.ctx, room_id
        room = self.room = self.ctx.rooms.get(room_id)
        super().__init__(parent, f"Take room {room.number} out of order",
                         "The room cannot be sold or checked into until it is returned to service.",
                         icon_name="slash", tone="orange", width=520)
        kinds = QVBoxLayout()
        self.maint = QRadioButton("Maintenance — short repair, back soon")
        self.oos = QRadioButton("Out of service — longer closure (renovation, damage)")
        self.maint.setChecked(True)
        kinds.addWidget(self.maint)
        kinds.addWidget(self.oos)
        self.body.addLayout(kinds)
        self.form = self.register_form(FormGrid(2))
        self.reason = line(placeholder="e.g. Water damage in bathroom", max_len=300)
        self.until = OptionalDateEdit(self.ctx.clock.today() + timedelta(days=3))
        self.form.add("reason", "Reason", self.reason, required=True, span=2)
        self.form.add("until", "Expected back", self.until, hint="Rooms can be sold again from this date")
        self.body.addWidget(self.form)
        self.add_cancel()
        self.add_footer_button("Take out of order", self._save, "danger", default=True)

    def _save(self) -> None:
        status = ServiceStatus.MAINTENANCE if self.maint.isChecked() else ServiceStatus.OUT_OF_SERVICE
        conflicts = self.attempt(lambda: self.ctx.rooms.set_service_status(
            self.room_id, status, self.reason.text(), self.until.value()), accept=False)
        if conflicts is None:
            return
        self.app.toast(f"Room {self.room.number} is now {ServiceStatus.LABELS[status].lower()}")
        self.accept()
        if isinstance(conflicts, list) and conflicts:
            self.app.actions.show_conflicts(self.room, conflicts)


class TicketDialog(BaseDialog):
    def __init__(self, parent, app, ticket_id: int | None = None, *, room_id: int | None = None):
        self.app, self.ctx, self.ticket_id = app, app.ctx, ticket_id
        t = self.ctx.maintenance.get(ticket_id) if ticket_id else None
        super().__init__(parent, f"Ticket #{t.id}" if t else "Report a maintenance issue",
                         t.title if t else "Describe the problem so maintenance can fix it.", icon_name="tool",
                         tone="orange", width=600)
        rooms = [("— Not a room (common area) —", None)] + [(f"Room {r.number} · {r.type_name}", r.id)
                                                                      for r in self.ctx.rooms.list_rooms()]
        self.form = self.register_form(FormGrid(2))
        self.form.add("title", "Issue", line(t.title if t else "", "e.g. Shower drain clogged", 120), required=True,
                      span=2)
        self.form.add("room_id", "Room", combo(rooms, t.room_id if t else room_id))
        self.form.add("location", "Location (if not a room)", line(t.location if t else "", "e.g. Ice machine, lobby",
                                                                   100))
        self.form.add("category", "Category", combo([(v, k) for k, v in TicketCategory.LABELS.items()],
                                                    t.category if t else "other"))
        self.form.add("priority", "Priority", combo([(v, k) for k, v in Priority.LABELS.items()],
                                                    t.priority if t else Priority.NORMAL))
        self.form.add("assigned_to", "Assigned to", line(t.assigned_to if t else "", "Staff member or vendor", 100))
        self.form.add("description", "Details", text_area(t.description if t else "", "What exactly is wrong?", 80),
                      span=2)
        blocks = QCheckBox("Take the room out of service until this is fixed")
        blocks.setChecked(t.blocks_room if t else False)
        can_block = self.ctx.can("maintenance.manage") or self.ctx.can("rooms.status")
        blocks.setEnabled(can_block)
        if not can_block:
            blocks.setToolTip("Only maintenance managers can block rooms.")
        self.form.add("blocks_room", "", blocks, span=2)
        self.body.addWidget(self.form)
        if t and t.status not in ("open", "in_progress", "on_hold"):
            self.body.addWidget(Banner(f"Closed: {t.resolution}", "info"))
            self.form.setEnabled(False)
        self.add_cancel("Close" if t else "Cancel")
        if not t or (t.status in ("open", "in_progress", "on_hold") and self.ctx.can("maintenance.manage")):
            self.add_footer_button("Save ticket" if t else "Create ticket", self._save, "primary", default=True)

    def _save(self) -> None:
        values = self.form.values()
        if self.ticket_id:
            conflicts = self.attempt(lambda: self.ctx.maintenance.update(self.ticket_id, values), accept=False)
            if conflicts is None:
                return
            self.app.toast("Ticket updated")
        else:
            result = self.attempt(lambda: self.ctx.maintenance.create(values), accept=False)
            if result is None:
                return
            ticket_id, conflicts = result
            self.app.toast(f"Ticket #{ticket_id} created")
        self.accept()
        if isinstance(conflicts, list) and conflicts and values.get("room_id"):
            self.app.actions.show_conflicts(self.ctx.rooms.get(values["room_id"]), conflicts)


class ResolveTicketDialog(BaseDialog):
    def __init__(self, parent, app, ticket_id: int, *, cancel: bool = False):
        self.app, self.ctx, self.ticket_id, self.cancel_mode = app, app.ctx, ticket_id, cancel
        t = self.ctx.maintenance.get(ticket_id)
        super().__init__(parent, f"{'Cancel' if cancel else 'Resolve'} ticket #{t.id}", f"{t.title} · {t.where}",
                         icon_name="slash" if cancel else "check-circle", tone="gray" if cancel else "green",
                         width=500)
        self.form = self.register_form(FormGrid(2))
        self.resolution = text_area("", "Why is it no longer needed?" if cancel else "What was done?", 70)
        self.form.add("resolution", "Reason" if cancel else "Resolution", self.resolution, required=True, span=2)
        self.cost = MoneyEdit()
        if not cancel:
            self.form.add("cost", "Cost (parts / vendor)", self.cost)
        self.body.addWidget(self.form)
        if t.blocks_room:
            self.body.addWidget(label("The room returns to service and is marked dirty for housekeeping (unless "
                                      "another open ticket still blocks it).", "faint", wrap=True))
        self.add_cancel("Back")
        self.add_footer_button("Cancel ticket" if cancel else "Mark resolved", self._save,
                               "danger" if cancel else "primary", default=True)

    def _save(self) -> None:
        if self.attempt(lambda: self.ctx.maintenance.resolve(self.ticket_id, self.resolution.toPlainText(),
                                                             self.cost.value() or None, cancelled=self.cancel_mode)):
            self.app.toast("Ticket closed")


class TaskDialog(BaseDialog):
    def __init__(self, parent, app, *, room_id: int | None = None, task_id: int | None = None):
        self.app, self.ctx, self.task_id = app, app.ctx, task_id
        task = self.ctx.housekeeping.get(task_id) if task_id else None
        super().__init__(parent, f"Task · Room {task.room_number}" if task else "New housekeeping task",
                         TaskType.LABELS[task.task_type] if task else "Schedule cleaning or an inspection.",
                         icon_name="sparkles", tone="teal", width=520)
        staff = [("Unassigned", None)] + [(u.full_name, u.id) for u in self.ctx.housekeeping.staff()]
        self.form = self.register_form(FormGrid(2))
        if not task:
            rooms = [(f"Room {r.number} · {r.type_name}", r.id) for r in self.ctx.rooms.list_rooms()]
            self.form.add("room_id", "Room", combo(rooms, room_id), required=True)
            self.form.add("task_type", "Task", combo([(v, k) for k, v in TaskType.LABELS.items()], "checkout"))
        self.form.add("priority", "Priority", combo([(v, k) for k, v in Priority.LABELS.items()],
                                                    task.priority if task else Priority.NORMAL))
        self.form.add("assigned_to", "Assign to", combo(staff, task.assigned_to if task else None))
        self.form.add("notes", "Notes", text_area(task.notes if task else "", "Anything the housekeeper should know",
                                                  70), span=2)
        self.body.addWidget(self.form)
        self.add_cancel()
        self.add_footer_button("Save" if task else "Create task", self._save, "primary", default=True)

    def _save(self) -> None:
        values = self.form.values()
        if self.task_id:
            ok = self.attempt(lambda: self.ctx.housekeeping.update_task(self.task_id, values))
        else:
            ok = self.attempt(lambda: self.ctx.housekeeping.create_task(values))
        if ok:
            self.app.toast("Task saved")


class AssignDialog(BaseDialog):
    def __init__(self, parent, app, task_ids: list[int]):
        self.app, self.ctx, self.task_ids = app, app.ctx, task_ids
        super().__init__(parent, "Assign housekeeper", f"{len(task_ids)} task(s) selected", icon_name="user",
                         tone="teal", width=420)
        staff = [("Unassigned", None)] + [(u.full_name, u.id) for u in self.ctx.housekeeping.staff()]
        self.form = self.register_form(FormGrid(1))
        self.who = combo(staff)
        self.form.add("assigned_to", "Housekeeper", self.who)
        self.body.addWidget(self.form)
        self.add_cancel()
        self.add_footer_button("Assign", self._save, "primary", default=True)

    def _save(self) -> None:
        if self.attempt(lambda: self.ctx.housekeeping.assign(self.task_ids, self.who.currentData())):
            self.app.toast("Tasks assigned")
