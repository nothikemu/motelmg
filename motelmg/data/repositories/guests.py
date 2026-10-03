from __future__ import annotations

from typing import Any

from motelmg.core.validation import digits_only
from motelmg.data.repositories.base import Repository, like
from motelmg.models import Guest, from_row

STAY_STATUSES = "('checked_in', 'checked_out')"

GUEST_SELECT = f"""
SELECT g.*,
  (SELECT COUNT(*) FROM reservations r WHERE r.guest_id = g.id AND r.status IN {STAY_STATUSES}) AS stays,
  (SELECT COALESCE(SUM(CAST(julianday(r.check_out_date) - julianday(r.check_in_date) AS INTEGER)), 0)
     FROM reservations r WHERE r.guest_id = g.id AND r.status IN {STAY_STATUSES}) AS nights,
  (SELECT MAX(r.check_in_date) FROM reservations r
     WHERE r.guest_id = g.id AND r.status IN {STAY_STATUSES}) AS last_stay,
  EXISTS(SELECT 1 FROM reservations r WHERE r.guest_id = g.id AND r.status = 'checked_in') AS in_house,
  (SELECT COALESCE(SUM(c.amount), 0) FROM charges c JOIN reservations r ON r.id = c.reservation_id
     WHERE r.guest_id = g.id AND c.is_void = 0) AS total_spent
FROM guests g
"""


class GuestRepository(Repository):
    def get(self, guest_id: int) -> Guest | None:
        row = self.db.one(f"{GUEST_SELECT} WHERE g.id = ?", (guest_id,))
        return from_row(Guest, row) if row else None

    def search(self, text: str = "", *, vip_only: bool = False, banned_only: bool = False,
               in_house_only: bool = False, limit: int = 1000) -> list[Guest]:
        where, params = ["1=1"], []
        text = (text or "").strip()
        if text:
            clauses = ["(g.first_name || ' ' || g.last_name) LIKE ? ESCAPE '\\'",
                       "(g.last_name || ' ' || g.first_name) LIKE ? ESCAPE '\\'",
                       "(g.last_name || ', ' || g.first_name) LIKE ? ESCAPE '\\'",
                       "g.email LIKE ? ESCAPE '\\'", "g.company LIKE ? ESCAPE '\\'",
                       "g.id_number LIKE ? ESCAPE '\\'", "g.vehicle_plate LIKE ? ESCAPE '\\'"]
            params += [like(text)] * len(clauses)
            digits = digits_only(text)
            if len(digits) >= 3:
                clauses.append("g.phone_digits LIKE ?")
                params.append(f"%{digits}%")
            where.append("(" + " OR ".join(clauses) + ")")
        if vip_only:
            where.append("g.is_vip = 1")
        if banned_only:
            where.append("g.is_banned = 1")
        if in_house_only:
            where.append("EXISTS(SELECT 1 FROM reservations r WHERE r.guest_id = g.id AND r.status = 'checked_in')")
        rows = self.db.query(
            f"{GUEST_SELECT} WHERE {' AND '.join(where)} "
            "ORDER BY g.last_name COLLATE NOCASE, g.first_name COLLATE NOCASE LIMIT ?", (*params, limit))
        return [from_row(Guest, r) for r in rows]

    def possible_duplicates(self, first: str, last: str, email: str, phone_digits: str,
                            id_number: str, exclude_id: int | None = None) -> list[Guest]:
        clauses, params = [], []
        if email:
            clauses.append("(g.email <> '' AND g.email = ? COLLATE NOCASE)")
            params.append(email)
        if len(phone_digits) >= 7:
            clauses.append("(g.phone_digits <> '' AND g.phone_digits = ?)")
            params.append(phone_digits)
        if id_number:
            clauses.append("(g.id_number <> '' AND g.id_number = ? COLLATE NOCASE)")
            params.append(id_number)
        if first and last:
            clauses.append("(g.first_name = ? COLLATE NOCASE AND g.last_name = ? COLLATE NOCASE)")
            params += [first, last]
        if not clauses:
            return []
        rows = self.db.query(
            f"{GUEST_SELECT} WHERE ({' OR '.join(clauses)}) AND g.id <> ? LIMIT 10", (*params, exclude_id or -1))
        return [from_row(Guest, r) for r in rows]

    def insert(self, values: dict[str, Any]) -> int:
        return self.db.insert("guests", values)

    def update(self, guest_id: int, values: dict[str, Any]) -> None:
        self.db.update("guests", guest_id, values)

    def delete(self, guest_id: int) -> None:
        self.db.execute("DELETE FROM guests WHERE id = ?", (guest_id,))

    def reservation_count(self, guest_id: int) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM reservations WHERE guest_id = ?", (guest_id,), 0))

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM guests", default=0))
