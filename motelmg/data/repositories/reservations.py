from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from motelmg.data.repositories.base import Repository, in_clause, like
from motelmg.models import Reservation, RoomMove, from_row

RES_SELECT = """
SELECT r.*,
       g.first_name || ' ' || g.last_name AS guest_name,
       g.phone AS guest_phone, g.email AS guest_email, g.is_vip AS guest_is_vip,
       rm.number AS room_number, t.name AS room_type_name,
       COALESCE(u.full_name, '') AS created_by_name,
       (SELECT COALESCE(SUM(c.amount), 0) FROM charges c
          WHERE c.reservation_id = r.id AND c.is_void = 0) AS total,
       (SELECT COALESCE(SUM(CASE WHEN p.kind = 'refund' THEN -p.amount ELSE p.amount END), 0)
          FROM payments p WHERE p.reservation_id = r.id AND p.is_void = 0) AS paid
FROM reservations r
JOIN guests g ON g.id = r.guest_id
JOIN rooms rm ON rm.id = r.room_id
JOIN room_types t ON t.id = rm.room_type_id
LEFT JOIN users u ON u.id = r.created_by
"""


def _build(rows) -> list[Reservation]:
    result = []
    for row in rows:
        res = from_row(Reservation, row)
        res.balance = res.total - res.paid
        result.append(res)
    return result


class ReservationRepository(Repository):
    def get(self, res_id: int) -> Reservation | None:
        rows = _build(self.db.query(f"{RES_SELECT} WHERE r.id = ?", (res_id,)))
        return rows[0] if rows else None

    def get_by_confirmation(self, number: str) -> Reservation | None:
        rows = _build(self.db.query(f"{RES_SELECT} WHERE r.confirmation_no = ? COLLATE NOCASE", (number,)))
        return rows[0] if rows else None

    def insert(self, values: dict[str, Any]) -> int:
        return self.db.insert("reservations", values)

    def update(self, res_id: int, values: dict[str, Any]) -> None:
        self.db.update("reservations", res_id, values)

    def search(self, *, text: str = "", statuses: Iterable[str] | None = None,
               arrival_from: date | None = None, arrival_to: date | None = None,
               stay_from: date | None = None, stay_to: date | None = None,
               departure_from: date | None = None, departure_to: date | None = None,
               guest_id: int | None = None, room_id: int | None = None, source: str = "",
               created_from: date | None = None, created_to: date | None = None,
               order: str = "r.check_in_date DESC, r.id DESC", limit: int = 5000) -> list[Reservation]:
        where, params = ["1=1"], []
        if text:
            text = text.strip()
            where.append("((g.first_name || ' ' || g.last_name) LIKE ? ESCAPE '\\' "
                         "OR (g.last_name || ' ' || g.first_name) LIKE ? ESCAPE '\\' "
                         "OR r.confirmation_no LIKE ? ESCAPE '\\' OR rm.number = ? COLLATE NOCASE "
                         "OR g.phone LIKE ? ESCAPE '\\' OR g.email LIKE ? ESCAPE '\\')")
            params += [like(text), like(text), like(text), text, like(text), like(text)]
        if statuses:
            clause, values = in_clause(list(statuses))
            where.append(f"r.status IN {clause}")
            params += values
        if arrival_from:
            where.append("r.check_in_date >= ?")
            params.append(arrival_from.isoformat())
        if arrival_to:
            where.append("r.check_in_date <= ?")
            params.append(arrival_to.isoformat())
        if departure_from:
            where.append("r.check_out_date >= ?")
            params.append(departure_from.isoformat())
        if departure_to:
            where.append("r.check_out_date <= ?")
            params.append(departure_to.isoformat())
        if stay_from:
            where.append("r.check_out_date > ?")
            params.append(stay_from.isoformat())
        if stay_to:
            where.append("r.check_in_date <= ?")
            params.append(stay_to.isoformat())
        if created_from:
            where.append("r.created_at >= ?")
            params.append(created_from.isoformat())
        if created_to:
            where.append("r.created_at < date(?, '+1 day')")
            params.append(created_to.isoformat())
        if guest_id:
            where.append("r.guest_id = ?")
            params.append(guest_id)
        if room_id:
            where.append("r.room_id = ?")
            params.append(room_id)
        if source:
            where.append("r.source = ?")
            params.append(source)
        rows = self.db.query(f"{RES_SELECT} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?",
                             (*params, limit))
        return _build(rows)

    def conflicts(self, room_id: int, check_in: date, check_out: date,
                  exclude_id: int | None = None) -> list[Reservation]:
        rows = self.db.query(
            f"{RES_SELECT} WHERE r.room_id = ? AND r.status IN ('confirmed', 'checked_in') "
            "AND r.check_in_date < ? AND r.check_out_date > ? AND r.id <> ? ORDER BY r.check_in_date",
            (room_id, check_out.isoformat(), check_in.isoformat(), exclude_id or -1))
        return _build(rows)

    def in_house(self) -> list[Reservation]:
        return _build(self.db.query(f"{RES_SELECT} WHERE r.status = 'checked_in' ORDER BY rm.number"))

    def in_house_for_room(self, room_id: int) -> Reservation | None:
        rows = _build(self.db.query(f"{RES_SELECT} WHERE r.status = 'checked_in' AND r.room_id = ?", (room_id,)))
        return rows[0] if rows else None

    def arrivals_pending(self, day: date) -> list[Reservation]:
        """Confirmed reservations due on/before ``day`` and not yet departed."""
        return _build(self.db.query(
            f"{RES_SELECT} WHERE r.status = 'confirmed' AND r.check_in_date <= ? AND r.check_out_date > ? "
            "ORDER BY r.check_in_date, rm.number", (day.isoformat(), day.isoformat())))

    def arrivals_on(self, day: date) -> list[Reservation]:
        return _build(self.db.query(
            f"{RES_SELECT} WHERE r.check_in_date = ? AND r.status IN ('confirmed', 'checked_in', 'checked_out') "
            "ORDER BY r.status = 'confirmed' DESC, r.expected_arrival, rm.number", (day.isoformat(),)))

    def departures_on(self, day: date) -> list[Reservation]:
        return _build(self.db.query(
            f"{RES_SELECT} WHERE ((r.check_out_date = ? AND r.status IN ('checked_in', 'checked_out')) "
            "OR (r.status = 'checked_in' AND r.check_out_date < ?)) "
            "ORDER BY r.status = 'checked_in' DESC, rm.number", (day.isoformat(), day.isoformat())))

    def stale_confirmed(self, day: date) -> list[Reservation]:
        """Confirmed reservations whose arrival date is before ``day`` (potential no-shows)."""
        return _build(self.db.query(
            f"{RES_SELECT} WHERE r.status = 'confirmed' AND r.check_in_date < ? ORDER BY r.check_in_date",
            (day.isoformat(),)))

    def room_moves(self, res_id: int) -> list[RoomMove]:
        rows = self.db.query(
            "SELECT m.*, f.number AS from_room, t.number AS to_room, COALESCE(u.full_name, '') AS moved_by_name "
            "FROM room_moves m JOIN rooms f ON f.id = m.from_room_id JOIN rooms t ON t.id = m.to_room_id "
            "LEFT JOIN users u ON u.id = m.moved_by WHERE m.reservation_id = ? ORDER BY m.moved_at", (res_id,))
        return [from_row(RoomMove, r) for r in rows]

    def add_room_move(self, res_id: int, from_room: int, to_room: int, ts: str, user_id: int | None,
                      reason: str) -> None:
        self.db.insert("room_moves", {"reservation_id": res_id, "from_room_id": from_room, "to_room_id": to_room,
                                      "moved_at": ts, "moved_by": user_id, "reason": reason})
