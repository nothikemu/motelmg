from __future__ import annotations

import html
import json

from PySide6.QtWidgets import QHBoxLayout

from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.common import SearchField, button, label
from motelmg.ui.widgets.date_range import DateRangePicker
from motelmg.ui.widgets.dialogs import inform
from motelmg.ui.widgets.forms import combo
from motelmg.ui.widgets.table import Column, DataTable

GROUP_LABELS = {"auth": "Sign-in", "reservations": "Reservations", "billing": "Billing", "guests": "Guests",
                "rooms": "Rooms", "housekeeping": "Housekeeping", "maintenance": "Maintenance", "staff": "Staff",
                "settings": "Settings", "backup": "Backups", "notes": "Notes", "setup": "Setup"}


class AuditPage(Page):
    key = "audit"
    title = "Audit Log"
    icon = "shield"
    permission = "audit.view"
    topics = ()

    def __init__(self, app):
        super().__init__(app)
        L = self.layout_
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.range = DateRangePicker(self.ctx.clock.today(), "7d")
        self.range.changed.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.range)
        self.user = combo([("All staff", None)])
        self.user.currentIndexChanged.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.user)
        self.group = combo([("All activity", "")])
        self.group.currentIndexChanged.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.group)
        self.search = SearchField("Search descriptions…")
        self.search.search.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.search, 1)
        bar.addWidget(button("Export", "download", on_click=lambda: self.export_table(self.table, "audit-log")))
        L.addLayout(bar)
        self.table = DataTable([
            Column("ts", "When", "datetime", width=170),
            Column("username", "Staff", width=110),
            Column("area", "Area", "badge", width=120, tone=lambda r: "indigo"),
            Column("action", "Action", width=190),
            Column("summary", "Description", stretch=True),
        ], self.fmt, empty_icon="shield", empty_title="No activity found",
            empty_text="Every important change is recorded here with the staff member who made it.")
        self.table.activated.connect(self._details)
        L.addWidget(self.table, 1)
        self.summary = label("", "faint")
        L.addWidget(self.summary)

    def subtitle(self) -> str:
        return "Who did what, and when"

    def refresh(self) -> None:
        current_user = self.user.currentData()
        self.user.blockSignals(True)
        self.user.clear()
        self.user.addItem("All staff", None)
        for u in self.ctx.users.list_users():
            self.user.addItem(u.full_name, u.id)
        self.user.setCurrentIndex(max(self.user.findData(current_user), 0))
        self.user.blockSignals(False)
        current_group = self.group.currentData()
        self.group.blockSignals(True)
        self.group.clear()
        self.group.addItem("All activity", "")
        for g in self.ctx.audit.action_groups():
            self.group.addItem(GROUP_LABELS.get(g, g.title()), g)
        self.group.setCurrentIndex(max(self.group.findData(current_group), 0))
        self.group.blockSignals(False)
        start, end = self.range.value()
        prefix = self.group.currentData()
        entries = self.ctx.audit.search(start=start, end=end, user_id=self.user.currentData(),
                                        action_prefix=f"{prefix}." if prefix else "", text=self.search.text().strip())
        self.table.set_rows([{"id": e.id, "ts": e.ts, "username": e.username,
                              "area": GROUP_LABELS.get(e.action.split(".")[0], e.action.split(".")[0].title()),
                              "action": e.action.split(".", 1)[-1].replace("_", " "), "summary": e.summary,
                              "details": e.details, "entity": e.entity_type, "entity_id": e.entity_id}
                             for e in entries])
        self.summary.setText(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}"
                             + (" (limited to 2000 — narrow the dates)" if len(entries) >= 2000 else "")
                             + " · double-click for details")

    def _details(self, row) -> None:
        if row["entity"] == "reservation" and row["entity_id"] and self.ctx.can("reservations.view"):
            self.actions.open_reservation(row["entity_id"], tab="history")
            return
        details = row["details"]
        try:
            pretty = json.dumps(json.loads(details), indent=2) if details else "No additional details."
        except ValueError:
            pretty = details
        inform(self, row["action"].capitalize(), f"<b>{html.escape(row['summary'])}</b><br><br>"
               f"<pre style='font-size:11px'>{html.escape(pretty)}</pre>")
