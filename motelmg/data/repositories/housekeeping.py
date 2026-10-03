from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from motelmg.data.repositories.base import Repository, in_clause
from motelmg.models import HKTask, from_row

TASK_SELECT = """
SELECT h.*, rm.number AS room_number, rm.floor, rm.hk_status, t.name AS room_type_name,
       COALESCE(a.full_name, '') AS assigned_name,
       COALESCE(c.full_name, '') AS completed_by_name,
       COALESCE(i.full_name, '') AS inspected_by_name,
       EXISTS(SELECT 1 FROM reservations r WHERE r.room_id = h.room_id AND r.status = 'confirmed'
              AND r.check_in_date <= :today AND r.check_out_date > :today) AS arrival_today,
       EXISTS(SELECT 1 FROM reservations r WHERE r.room_id = h.room_id AND r.status = 'checked_in') AS occupied
FROM housekeeping_tasks h
JOIN rooms rm ON rm.id = h.room_id
JOIN room_types t ON t.id = rm.room_type_id
LEFT JOIN users a ON a.id = h.assigned_to
LEFT JOIN users c ON c.id = h.completed_by
LEFT JOIN users i ON i.id = h.inspected_by
"""


class HousekeepingRepository(Repository):
    def get(self, task_id: int, today: date) -> HKTask | None:
        row = self.db.one(f"{TASK_SELECT} WHERE h.id = :id", {"id": task_id, "today": today.isoformat()})
        return from_row(HKTask, row) if row else None

    def search(self, today: date, *, statuses: Iterable[str] | None = None, assigned_to: int | None = None,
               room_id: int | None = None, start: date | None = None, end: date | None = None,
               unassigned_only: bool = False, limit: int = 5000) -> list[HKTask]:
        where = ["1=1"]
        params: dict[str, Any] = {"today": today.isoformat(), "limit": limit}
        if statuses:
            clause, values = in_clause(list(statuses))
            names = []
            for idx, value in enumerate(values):
                params[f"s{idx}"] = value
                names.append(f":s{idx}")
            where.append(f"h.status IN ({', '.join(names)})")
        if assigned_to:
            where.append("h.assigned_to = :assigned")
            params["assigned"] = assigned_to
        if unassigned_only:
            where.append("h.assigned_to IS NULL")
        if room_id:
            where.append("h.room_id = :room")
            params["room"] = room_id
        if start:
            where.append("COALESCE(h.completed_at, h.created_at) >= :start")
            params["start"] = start.isoformat()
        if end:
            where.append("COALESCE(h.completed_at, h.created_at) < date(:end, '+1 day')")
            params["end"] = end.isoformat()
        rows = self.db.query(
            f"{TASK_SELECT} WHERE {' AND '.join(where)} "
            "ORDER BY CASE WHEN h.status IN ('pending','in_progress') THEN 0 ELSE 1 END, "
            "h.priority, arrival_today DESC, h.created_at DESC LIMIT :limit", params)
        return [from_row(HKTask, r) for r in rows]

    def open_task(self, room_id: int, task_type: str | None = None):
        sql = "SELECT * FROM housekeeping_tasks WHERE room_id = ? AND status IN ('pending', 'in_progress')"
        params: list[Any] = [room_id]
        if task_type:
            sql += " AND task_type = ?"
            params.append(task_type)
        return self.db.query(sql + " ORDER BY priority, id", params)

    def insert(self, values: dict[str, Any]) -> int:
        return self.db.insert("housekeeping_tasks", values)

    def update(self, task_id: int, values: dict[str, Any]) -> None:
        self.db.update("housekeeping_tasks", task_id, values)
