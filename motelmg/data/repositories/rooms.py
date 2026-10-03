from __future__ import annotations

from datetime import date
from typing import Any

from motelmg.data.repositories.base import Repository, natural_key
from motelmg.models import Room, RoomType, from_row

ROOM_SELECT = (
    "SELECT r.*, t.name AS type_name, t.code AS type_code, t.beds AS type_beds, "
    "t.max_occupancy AS type_max_occupancy, t.base_rate AS type_rate "
    "FROM rooms r JOIN room_types t ON t.id = r.room_type_id"
)


def _sort_rooms(rooms: list[Room]) -> list[Room]:
    return sorted(rooms, key=lambda r: (natural_key(r.floor), r.sort_order, natural_key(r.number)))


class RoomRepository(Repository):
    # -- room types ---------------------------------------------------------
    def list_types(self, include_inactive: bool = False) -> list[RoomType]:
        where = "" if include_inactive else "WHERE t.is_active = 1"
        rows = self.db.query(
            "SELECT t.*, (SELECT COUNT(*) FROM rooms r WHERE r.room_type_id = t.id AND r.is_active = 1) "
            f"AS room_count FROM room_types t {where} ORDER BY t.sort_order, t.name COLLATE NOCASE")
        return [from_row(RoomType, r) for r in rows]

    def get_type(self, type_id: int) -> RoomType | None:
        row = self.db.one(
            "SELECT t.*, (SELECT COUNT(*) FROM rooms r WHERE r.room_type_id = t.id AND r.is_active = 1) "
            "AS room_count FROM room_types t WHERE t.id = ?", (type_id,))
        return from_row(RoomType, row) if row else None

    def insert_type(self, values: dict[str, Any]) -> int:
        return self.db.insert("room_types", values)

    def update_type(self, type_id: int, values: dict[str, Any]) -> None:
        self.db.update("room_types", type_id, values)

    def delete_type(self, type_id: int) -> None:
        self.db.execute("DELETE FROM room_types WHERE id = ?", (type_id,))

    def type_in_use(self, type_id: int) -> bool:
        return bool(self.db.scalar(
            "SELECT EXISTS(SELECT 1 FROM rooms WHERE room_type_id = ?) "
            "OR EXISTS(SELECT 1 FROM reservations WHERE room_type_id = ?)", (type_id, type_id)))

    # -- rooms ------------------------------------------------------------------
    def list_rooms(self, include_inactive: bool = False) -> list[Room]:
        where = "" if include_inactive else "WHERE r.is_active = 1"
        rows = self.db.query(f"{ROOM_SELECT} {where}")
        return _sort_rooms([from_row(Room, r) for r in rows])

    def get_room(self, room_id: int) -> Room | None:
        row = self.db.one(f"{ROOM_SELECT} WHERE r.id = ?", (room_id,))
        return from_row(Room, row) if row else None

    def get_by_number(self, number: str) -> Room | None:
        row = self.db.one(f"{ROOM_SELECT} WHERE r.number = ? COLLATE NOCASE", (number,))
        return from_row(Room, row) if row else None

    def insert_room(self, values: dict[str, Any]) -> int:
        return self.db.insert("rooms", values)

    def update_room(self, room_id: int, values: dict[str, Any]) -> None:
        self.db.update("rooms", room_id, values)

    def delete_room(self, room_id: int) -> None:
        self.db.execute("DELETE FROM rooms WHERE id = ?", (room_id,))

    def room_has_history(self, room_id: int) -> bool:
        return bool(self.db.scalar("SELECT EXISTS(SELECT 1 FROM reservations WHERE room_id = ?) "
                                   "OR EXISTS(SELECT 1 FROM charges WHERE room_id = ?)", (room_id, room_id)))

    def count_active_rooms(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM rooms WHERE is_active = 1", default=0))

    def booked_room_ids(self, check_in: date, check_out: date, exclude_reservation: int | None = None) -> set[int]:
        rows = self.db.query(
            "SELECT DISTINCT room_id FROM reservations WHERE status IN ('confirmed', 'checked_in') "
            "AND check_in_date < ? AND check_out_date > ? AND id <> ?",
            (check_out.isoformat(), check_in.isoformat(), exclude_reservation or -1))
        return {r[0] for r in rows}

    def occupied_room_ids(self) -> set[int]:
        return {r[0] for r in self.db.query("SELECT room_id FROM reservations WHERE status = 'checked_in'")}

    def future_reservations(self, room_id: int, from_date: date, until: date | None = None):
        sql = ("SELECT r.id, r.confirmation_no, r.check_in_date, r.check_out_date, r.status, "
               "g.first_name || ' ' || g.last_name AS guest_name FROM reservations r "
               "JOIN guests g ON g.id = r.guest_id WHERE r.room_id = ? AND r.status = 'confirmed' "
               "AND r.check_out_date > ?")
        params: list[Any] = [room_id, from_date.isoformat()]
        if until:
            sql += " AND r.check_in_date <= ?"
            params.append(until.isoformat())
        return self.db.query(sql + " ORDER BY r.check_in_date", params)

    # -- status log ---------------------------------------------------------------
    def log_status(self, room_id: int, field: str, old: str, new: str, reason: str, user_id: int | None,
                   ts: str) -> None:
        self.db.execute(
            "INSERT INTO room_status_log(room_id, ts, user_id, field, old_value, new_value, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (room_id, ts, user_id, field, old or "", new, reason))

    def status_history(self, room_id: int, limit: int = 200):
        return self.db.query(
            "SELECT l.*, COALESCE(u.full_name, 'System') AS user_name FROM room_status_log l "
            "LEFT JOIN users u ON u.id = l.user_id WHERE l.room_id = ? ORDER BY l.ts DESC, l.id DESC LIMIT ?",
            (room_id, limit))
