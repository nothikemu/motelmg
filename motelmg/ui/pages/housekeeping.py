from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout

from motelmg.core.enums import Priority, TaskStatus, TaskType
from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.common import ChipGroup, StatCard, button, label
from motelmg.ui.widgets.dialogs import ask_text, confirm, guarded
from motelmg.ui.widgets.forms import combo
from motelmg.ui.widgets.table import Column, DataTable


class HousekeepingPage(Page):
    key = "housekeeping"
    title = "Housekeeping"
    icon = "sparkles"
    permission = "housekeeping.view"
    topics = ("housekeeping", "rooms", "reservations")

    def __init__(self, app):
        super().__init__(app)
        ctx = self.ctx
        L = self.layout_
        stats = QGridLayout()
        stats.setSpacing(14)
        self.s_dirty = StatCard("DIRTY ROOMS", "alert-circle", "amber")
        self.s_cleaning = StatCard("BEING CLEANED", "sparkles", "cyan")
        self.s_inspect = StatCard("CLEAN, NOT INSPECTED", "eye", "purple")
        self.s_ready = StatCard("INSPECTED", "check-circle", "green")
        self.s_done = StatCard("COMPLETED TODAY", "check", "teal")
        for i, card in enumerate((self.s_dirty, self.s_cleaning, self.s_inspect, self.s_ready, self.s_done)):
            stats.addWidget(card, 0, i)
        L.addLayout(stats)
        top = QHBoxLayout()
        top.setSpacing(10)
        chips = [("Open tasks", "open")]
        if ctx.can("housekeeping.work") and not ctx.can("housekeeping.manage"):
            chips.insert(0, ("My tasks", "mine"))
        chips += [("Awaiting inspection", "inspect"), ("Unassigned", "unassigned"), ("Done today", "done"),
                  ("History", "history")]
        self.chips = ChipGroup(chips)
        self.chips.changed.connect(lambda *_: self.mark_stale())
        top.addWidget(self.chips)
        top.addStretch(1)
        self.assignee = combo([("Everyone", None)])
        self.assignee.currentIndexChanged.connect(lambda *_: self.mark_stale())
        top.addWidget(self.assignee)
        if ctx.can("housekeeping.manage"):
            top.addWidget(button("Generate daily tasks", "refresh", on_click=self._generate,
                                 tooltip="Stayover service for occupied rooms + cleaning for dirty rooms"))
            top.addWidget(button("New task", "plus", "primary", on_click=self._new_task))
        L.addLayout(top)
        self.table = DataTable([
            Column("priority", "Priority", "badge", width=92, fmt=lambda r: Priority.LABELS[r["priority"]],
                   tone=lambda r: Priority.TONES[r["priority"]], sort=lambda r: r["priority"]),
            Column("room", "Room", width=66, bold=True, sort=lambda r: r["room_sort"]),
            Column("room_type", "Room type", width=130),
            Column("task", "Task", width=130),
            Column("status", "Status", "badge", width=120, fmt=lambda r: r["status_label"], tone=lambda r: r["tone"]),
            Column("assigned", "Assigned to", width=130),
            Column("flags", "", width=150),
            Column("created_at", "Created", "datetime", width=150),
            Column("notes", "Notes", stretch=True),
        ], self.fmt, empty_icon="sparkles", empty_title="No housekeeping tasks",
            empty_text="Tasks are created automatically when guests check out or rooms are marked dirty.",
            multi_select=True)
        self.table.activated.connect(self._activate)
        self.table.set_menu_builder(self._menu)
        self.table.selection_changed.connect(self._update_buttons)
        L.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        self.summary = label("", "faint")
        bottom.addWidget(self.summary)
        bottom.addStretch(1)
        self.btn_assign = button("Assign…", "user", small=True, on_click=self._assign)
        self.btn_start = button("Start", "play", small=True, on_click=self._start)
        self.btn_done = button("Mark complete", "check", "primary", small=True, on_click=self._complete)
        self.btn_pass = button("Pass inspection", "check-circle", small=True, on_click=lambda: self._inspect(True))
        self.btn_fail = button("Fail", "x", "danger-outline", small=True, on_click=lambda: self._inspect(False))
        self.btn_cancel = button("Cancel task", "slash", "ghost", small=True, on_click=self._cancel)
        for b, perm in ((self.btn_assign, "housekeeping.manage"), (self.btn_start, None), (self.btn_done, None),
                        (self.btn_pass, "housekeeping.inspect"), (self.btn_fail, "housekeeping.inspect"),
                        (self.btn_cancel, "housekeeping.manage")):
            if perm is None:
                b.setVisible(ctx.can("housekeeping.work") or ctx.can("housekeeping.manage"))
            else:
                b.setVisible(ctx.can(perm))
            bottom.addWidget(b)
        L.addLayout(bottom)
        self._update_buttons()

    def subtitle(self) -> str:
        return "Room cleaning, assignments and inspections"

    def refresh(self) -> None:
        ctx = self.ctx
        s = ctx.housekeeping.summary()
        self.s_dirty.set(str(s.dirty), "need cleaning", "amber" if s.dirty else "green")
        self.s_cleaning.set(str(s.cleaning), f"{s.in_progress_tasks} task(s) in progress")
        self.s_inspect.set(str(s.awaiting_inspection), "vacant rooms awaiting inspection")
        self.s_ready.set(str(s.inspected), "rooms inspected and ready")
        self.s_done.set(str(s.completed_today), f"{s.pending_tasks} pending · {s.unassigned} unassigned")
        current = self.assignee.currentData()
        self.assignee.blockSignals(True)
        self.assignee.clear()
        self.assignee.addItem("Everyone", None)
        for u in ctx.housekeeping.staff():
            self.assignee.addItem(u.full_name, u.id)
        self.assignee.setCurrentIndex(max(self.assignee.findData(current), 0))
        self.assignee.blockSignals(False)
        mode = self.chips.current()
        today = ctx.clock.today()
        assigned = self.assignee.currentData()
        if mode == "mine":
            tasks = ctx.housekeeping.tasks(statuses=TaskStatus.OPEN, assigned_to=ctx.user_id) + \
                ctx.housekeeping.tasks(statuses=TaskStatus.OPEN, unassigned_only=True)
        elif mode == "open":
            tasks = ctx.housekeeping.tasks(statuses=TaskStatus.OPEN, assigned_to=assigned)
        elif mode == "unassigned":
            tasks = ctx.housekeeping.tasks(statuses=TaskStatus.OPEN, unassigned_only=True)
        elif mode == "inspect":
            tasks = ctx.housekeeping.awaiting_inspection(assigned)
        elif mode == "done":
            tasks = ctx.housekeeping.tasks(statuses=[TaskStatus.COMPLETED, TaskStatus.INSPECTED], start=today,
                                           end=today, assigned_to=assigned)
        else:
            tasks = ctx.housekeeping.tasks(assigned_to=assigned)
        rows = []
        from motelmg.data.repositories.base import natural_key
        for t in tasks:
            flags = []
            if t.arrival_today and t.status in TaskStatus.OPEN:
                flags.append("Arrival today")
            if t.occupied:
                flags.append("Occupied")
            if t.inspection_notes and t.status == TaskStatus.PENDING:
                flags.append("Redo")
            status_label = TaskStatus.LABELS[t.status]
            tone = TaskStatus.TONES[t.status]
            if mode == "inspect":
                status_label, tone = "Needs inspection", "purple"
            rows.append({"id": t.id, "priority": t.priority, "room": t.room_number,
                         "room_sort": natural_key(t.room_number), "room_type": t.room_type_name,
                         "task": TaskType.LABELS[t.task_type], "status": t.status, "status_label": status_label,
                         "tone": tone, "assigned": t.assigned_name or "—", "flags": " · ".join(flags),
                         "created_at": t.created_at, "notes": (t.inspection_notes and f"Inspection: {t.inspection_notes}"
                                                               ) or t.notes.replace("\n", " "),
                         "task_obj": t})
        self.table.set_rows(rows)
        self.summary.setText(f"{len(rows)} task(s)")
        self._update_buttons()

    def _selected(self) -> list[dict]:
        return self.table.selected_rows()

    def _update_buttons(self) -> None:
        rows = self._selected()
        statuses = {r["status"] for r in rows}
        one = len(rows) == 1
        self.btn_assign.setEnabled(bool(rows) and statuses <= set(TaskStatus.OPEN))
        self.btn_start.setEnabled(one and statuses == {TaskStatus.PENDING})
        self.btn_done.setEnabled(one and statuses <= set(TaskStatus.OPEN) and bool(statuses))
        inspectable = one and rows[0]["status"] == TaskStatus.COMPLETED
        self.btn_pass.setEnabled(inspectable)
        self.btn_fail.setEnabled(inspectable)
        self.btn_cancel.setEnabled(one and statuses <= set(TaskStatus.OPEN) and bool(statuses))

    def _activate(self, row) -> None:
        if row["status"] == TaskStatus.PENDING:
            self._start()
        elif row["status"] == TaskStatus.IN_PROGRESS:
            self._complete()
        elif self.ctx.can("housekeeping.manage") and row["status"] in TaskStatus.OPEN:
            from motelmg.ui.dialogs.property import TaskDialog
            TaskDialog(self, self.app, task_id=row["id"]).exec()

    def _menu(self, row) -> list:
        can = self.ctx.can
        open_ = row["status"] in TaskStatus.OPEN
        return [
            ("Start cleaning", self._start, row["status"] == TaskStatus.PENDING),
            ("Mark complete", self._complete, open_),
            ("Pass inspection", lambda: self._inspect(True),
             row["status"] == TaskStatus.COMPLETED and can("housekeeping.inspect")),
            ("Fail inspection…", lambda: self._inspect(False),
             row["status"] == TaskStatus.COMPLETED and can("housekeeping.inspect")),
            None,
            ("Assign…", self._assign, open_ and can("housekeeping.manage")),
            ("Edit task…", lambda: self._edit(row), open_ and can("housekeeping.manage")),
            ("Cancel task…", self._cancel, open_ and can("housekeeping.manage")),
            None,
            ("Show room on board", lambda: self.actions.open_room(row["task_obj"].room_id)),
        ]

    def _edit(self, row) -> None:
        from motelmg.ui.dialogs.property import TaskDialog
        TaskDialog(self, self.app, task_id=row["id"]).exec()

    def _new_task(self) -> None:
        from motelmg.ui.dialogs.property import TaskDialog
        TaskDialog(self, self.app).exec()

    def _generate(self) -> None:
        count = guarded(self, self.ctx.housekeeping.generate_daily_tasks)
        if count is not None:
            self.app.toast(f"{count if count is not True else 0} task(s) created" if count else "No new tasks needed",
                           "success" if count else "info")

    def _assign(self) -> None:
        rows = self._selected()
        if rows:
            from motelmg.ui.dialogs.property import AssignDialog
            AssignDialog(self, self.app, [r["id"] for r in rows]).exec()

    def _start(self) -> None:
        rows = self._selected()
        if rows:
            guarded(self, lambda: self.ctx.housekeeping.start(rows[0]["id"]), f"Started room {rows[0]['room']}",
                    self.app.toast)

    def _complete(self) -> None:
        rows = self._selected()
        if rows:
            guarded(self, lambda: self.ctx.housekeeping.complete(rows[0]["id"]),
                    f"Room {rows[0]['room']} is clean", self.app.toast)

    def _inspect(self, passed: bool) -> None:
        rows = self._selected()
        if not rows:
            return
        notes = ""
        if not passed:
            notes = ask_text(self, "Failed inspection", "What needs to be redone?", multiline=True,
                             confirm_text="Send back", danger=True)
            if not notes:
                return
        guarded(self, lambda: self.ctx.housekeeping.inspect(rows[0]["id"], passed, notes),
                f"Room {rows[0]['room']} {'passed' if passed else 'failed'} inspection", self.app.toast)

    def _cancel(self) -> None:
        rows = self._selected()
        if rows and confirm(self, "Cancel task", f"Cancel the {rows[0]['task'].lower()} task for room "
                            f"{rows[0]['room']}?", "Cancel task", danger=True):
            guarded(self, lambda: self.ctx.housekeeping.cancel(rows[0]["id"], "Cancelled by staff"),
                    "Task cancelled", self.app.toast)
