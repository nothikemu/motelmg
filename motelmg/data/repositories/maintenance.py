from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from motelmg.data.repositories.base import Repository, in_clause, like
from motelmg.models import MaintenanceTicket, from_row

TICKET_SELECT = """
SELECT m.*, COALESCE(rm.number, '') AS room_number,
       COALESCE(u.full_name, '') AS reported_by_name,
       COALESCE(v.full_name, '') AS resolved_by_name
FROM maintenance_tickets m
LEFT JOIN rooms rm ON rm.id = m.room_id
LEFT JOIN users u ON u.id = m.reported_by
LEFT JOIN users v ON v.id = m.resolved_by
"""


class MaintenanceRepository(Repository):
    def get(self, ticket_id: int) -> MaintenanceTicket | None:
        row = self.db.one(f"{TICKET_SELECT} WHERE m.id = ?", (ticket_id,))
        return from_row(MaintenanceTicket, row) if row else None

    def search(self, *, statuses: Iterable[str] | None = None, room_id: int | None = None, category: str = "",
               priority: int | None = None, text: str = "", start: date | None = None, end: date | None = None,
               limit: int = 5000) -> list[MaintenanceTicket]:
        where, params = ["1=1"], []
        if statuses:
            clause, values = in_clause(list(statuses))
            where.append(f"m.status IN {clause}")
            params += values
        if room_id:
            where.append("m.room_id = ?")
            params.append(room_id)
        if category:
            where.append("m.category = ?")
            params.append(category)
        if priority:
            where.append("m.priority = ?")
            params.append(priority)
        if start:
            where.append("m.created_at >= ?")
            params.append(start.isoformat())
        if end:
            where.append("m.created_at < date(?, '+1 day')")
            params.append(end.isoformat())
        if text:
            where.append("(m.title LIKE ? ESCAPE '\\' OR m.description LIKE ? ESCAPE '\\' "
                         "OR m.location LIKE ? ESCAPE '\\' OR rm.number = ? COLLATE NOCASE "
                         "OR m.assigned_to LIKE ? ESCAPE '\\' OR CAST(m.id AS TEXT) = ?)")
            params += [like(text), like(text), like(text), text, like(text), text.lstrip("#")]
        rows = self.db.query(
            f"{TICKET_SELECT} WHERE {' AND '.join(where)} "
            "ORDER BY CASE WHEN m.status IN ('open','in_progress','on_hold') THEN 0 ELSE 1 END, "
            "m.priority, m.created_at DESC LIMIT ?", (*params, limit))
        return [from_row(MaintenanceTicket, r) for r in rows]

    def insert(self, values: dict[str, Any]) -> int:
        return self.db.insert("maintenance_tickets", values)

    def update(self, ticket_id: int, values: dict[str, Any]) -> None:
        self.db.update("maintenance_tickets", ticket_id, values)

    def active_blocking_count(self, room_id: int, exclude_id: int | None = None) -> int:
        return int(self.db.scalar(
            "SELECT COUNT(*) FROM maintenance_tickets WHERE room_id = ? AND blocks_room = 1 "
            "AND status IN ('open', 'in_progress', 'on_hold') AND id <> ?", (room_id, exclude_id or -1), 0))

    def open_count_by_room(self) -> dict[int, int]:
        return {r[0]: r[1] for r in self.db.query(
            "SELECT room_id, COUNT(*) FROM maintenance_tickets WHERE room_id IS NOT NULL "
            "AND status IN ('open', 'in_progress', 'on_hold') GROUP BY room_id")}
