from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout

from motelmg.core.enums import Priority, ServiceStatus, TicketCategory, TicketStatus
from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.common import Card, ChipGroup, SearchField, button, label
from motelmg.ui.widgets.dialogs import confirm, guarded
from motelmg.ui.widgets.forms import combo
from motelmg.ui.widgets.table import Column, DataTable


class MaintenancePage(Page):
    key = "maintenance"
    title = "Maintenance"
    icon = "tool"
    permission = "maintenance.view"
    topics = ("maintenance", "rooms")

    def __init__(self, app):
        super().__init__(app)
        ctx = self.ctx
        L = self.layout_
        top = QHBoxLayout()
        top.setSpacing(10)
        self.chips = ChipGroup([("Open", "active"), ("Urgent", "urgent"), ("Room blocked", "blocking"),
                                ("Resolved", "resolved"), ("All", "all")])
        self.chips.changed.connect(lambda *_: self.mark_stale())
        top.addWidget(self.chips)
        top.addStretch(1)
        self.category = combo([("All categories", "")] + [(v, k) for k, v in TicketCategory.LABELS.items()])
        self.category.currentIndexChanged.connect(lambda *_: self.mark_stale())
        top.addWidget(self.category)
        self.search = SearchField("Ticket #, room, issue…")
        self.search.search.connect(lambda *_: self.mark_stale())
        top.addWidget(self.search)
        top.addWidget(button("Export", "download", on_click=lambda: self.export_table(self.table, "maintenance")))
        if ctx.can("maintenance.report"):
            top.addWidget(button("Report issue", "plus", "primary", on_click=lambda: self.actions.new_ticket()))
        L.addLayout(top)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.table = DataTable([
            Column("ticket", "#", width=52, bold=True, sort=lambda r: r["id"]),
            Column("priority", "Priority", "badge", width=84, fmt=lambda r: Priority.LABELS[r["priority"]],
                   tone=lambda r: Priority.TONES[r["priority"]], sort=lambda r: r["priority"]),
            Column("where", "Location", width=96),
            Column("title", "Issue", stretch=True),
            Column("category", "Category", width=120),
            Column("status", "Status", "badge", width=104, fmt=lambda r: r["status_label"],
                   tone=lambda r: r["tone"]),
            Column("assigned_to", "Assigned", width=110),
            Column("created_at", "Opened", "datetime", width=146),
        ], self.fmt, empty_icon="tool", empty_title="No maintenance tickets",
            empty_text="Report broken fixtures, appliances or anything that needs repair.")
        self.table.activated.connect(lambda r: self.actions.open_ticket(r["id"]))
        self.table.set_menu_builder(self._menu)
        self.table.selection_changed.connect(self._update_buttons)
        body.addWidget(self.table, 1)
        self.ooo_card = Card("Rooms out of order", icon_name="slash")
        self.ooo_card.setFixedWidth(270)
        self.ooo_table = DataTable([
            Column("number", "Room", width=60, bold=True),
            Column("status", "Status", "badge", width=110, fmt=lambda r: ServiceStatus.LABELS[r["status"]],
                   tone=lambda r: ServiceStatus.TONES[r["status"]]),
            Column("reason", "Reason", stretch=True),
        ], self.fmt, empty_icon="check-circle", empty_title="All rooms in service", row_height=34)
        self.ooo_table.activated.connect(lambda r: self.actions.open_room(r["id"]))
        self.ooo_card.body.addWidget(self.ooo_table)
        self.ooo_card.body.addWidget(label("Double-click to open the room on the board.", "faint", wrap=True))
        body.addWidget(self.ooo_card)
        L.addLayout(body, 1)
        bottom = QHBoxLayout()
        self.summary = label("", "faint")
        bottom.addWidget(self.summary)
        bottom.addStretch(1)
        manage = ctx.can("maintenance.manage")
        self.btn_progress = button("Start work", "play", small=True,
                                   on_click=lambda: self._status(TicketStatus.IN_PROGRESS))
        self.btn_hold = button("On hold", "clock", small=True, on_click=lambda: self._status(TicketStatus.ON_HOLD))
        self.btn_resolve = button("Resolve…", "check-circle", "primary", small=True, on_click=self._resolve)
        self.btn_cancel = button("Cancel…", "slash", "ghost", small=True, on_click=lambda: self._resolve(True))
        for b in (self.btn_progress, self.btn_hold, self.btn_resolve, self.btn_cancel):
            b.setVisible(manage)
            bottom.addWidget(b)
        L.addLayout(bottom)
        self._update_buttons()

    def subtitle(self) -> str:
        return "Repairs, room blocks and maintenance history"

    def refresh(self) -> None:
        mode = self.chips.current()
        statuses = {"active": TicketStatus.ACTIVE, "urgent": TicketStatus.ACTIVE, "blocking": TicketStatus.ACTIVE,
                    "resolved": [TicketStatus.RESOLVED, TicketStatus.CANCELLED], "all": None}[mode]
        tickets = self.ctx.maintenance.search(statuses=statuses, category=self.category.currentData() or "",
                                              text=self.search.text().strip(),
                                              priority=Priority.URGENT if mode == "urgent" else None)
        if mode == "blocking":
            tickets = [t for t in tickets if t.blocks_room]
        rows = [{"id": t.id, "ticket": f"#{t.id}", "priority": t.priority, "where": t.where, "title": t.title,
                 "category": TicketCategory.LABELS.get(t.category, t.category), "status": t.status,
                 "status_label": "Room blocked" if t.blocks_room and t.status in TicketStatus.ACTIVE
                 else TicketStatus.LABELS[t.status],
                 "tone": "orange" if t.blocks_room and t.status in TicketStatus.ACTIVE else TicketStatus.TONES[t.status],
                 "assigned_to": t.assigned_to or "—", "created_at": t.created_at} for t in tickets]
        self.table.set_rows(rows)
        self.summary.setText(f"{len(rows)} ticket(s)")
        rooms = [r for r in self.ctx.rooms.list_rooms() if r.service_status != ServiceStatus.IN_SERVICE]
        self.ooo_table.set_rows([{"id": r.id, "number": r.number, "status": r.service_status,
                                  "reason": r.service_reason} for r in rooms])
        self._update_buttons()

    def _update_buttons(self) -> None:
        row = self.table.selected_row()
        active = bool(row and row["status"] in TicketStatus.ACTIVE)
        self.btn_progress.setEnabled(active and row["status"] != TicketStatus.IN_PROGRESS)
        self.btn_hold.setEnabled(active and row["status"] != TicketStatus.ON_HOLD)
        self.btn_resolve.setEnabled(active)
        self.btn_cancel.setEnabled(active)

    def _menu(self, row) -> list:
        manage = self.ctx.can("maintenance.manage")
        active = row["status"] in TicketStatus.ACTIVE
        return [("Open ticket", lambda: self.actions.open_ticket(row["id"])),
                None,
                ("Start work", lambda: self._status(TicketStatus.IN_PROGRESS), manage and active),
                ("Put on hold", lambda: self._status(TicketStatus.ON_HOLD), manage and active),
                ("Resolve…", self._resolve, manage and active),
                ("Cancel ticket…", lambda: self._resolve(True), manage and active)]

    def _status(self, status: str) -> None:
        row = self.table.selected_row()
        if row:
            guarded(self, lambda: self.ctx.maintenance.set_status(row["id"], status),
                    f"Ticket #{row['id']} → {TicketStatus.LABELS[status]}", self.app.toast)

    def _resolve(self, cancel: bool = False) -> None:
        row = self.table.selected_row()
        if not row:
            return
        from motelmg.ui.dialogs.property import ResolveTicketDialog
        ResolveTicketDialog(self, self.app, row["id"], cancel=cancel).exec()


__all__ = ["MaintenancePage", "confirm"]
