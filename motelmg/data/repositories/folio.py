from __future__ import annotations

from datetime import date
from typing import Any

from motelmg.data.repositories.base import Repository, like
from motelmg.models import (Charge, ChargeItem, DiscountType, Payment, PaymentMethod, Tax, from_row)

PAYMENT_SELECT = """
SELECT p.*, m.name AS method_name, COALESCE(u.full_name, '') AS created_by_name,
       r.confirmation_no, g.first_name || ' ' || g.last_name AS guest_name, rm.number AS room_number
FROM payments p
JOIN payment_methods m ON m.id = p.method_id
JOIN reservations r ON r.id = p.reservation_id
JOIN guests g ON g.id = r.guest_id
JOIN rooms rm ON rm.id = r.room_id
LEFT JOIN users u ON u.id = p.created_by
"""


class FolioRepository(Repository):
    # -- catalog -----------------------------------------------------------------
    def taxes(self, include_inactive: bool = False) -> list[Tax]:
        where = "" if include_inactive else "WHERE is_active = 1"
        return [from_row(Tax, r) for r in self.db.query(f"SELECT * FROM taxes {where} ORDER BY sort_order, id")]

    def charge_items(self, include_inactive: bool = False) -> list[ChargeItem]:
        where = "" if include_inactive else "WHERE is_active = 1"
        return [from_row(ChargeItem, r) for r in self.db.query(
            f"SELECT * FROM charge_items {where} ORDER BY sort_order, name COLLATE NOCASE")]

    def charge_item_by_code(self, code: str) -> ChargeItem | None:
        row = self.db.one("SELECT * FROM charge_items WHERE system_code = ?", (code,))
        return from_row(ChargeItem, row) if row else None

    def charge_item(self, item_id: int) -> ChargeItem | None:
        row = self.db.one("SELECT * FROM charge_items WHERE id = ?", (item_id,))
        return from_row(ChargeItem, row) if row else None

    def discount_types(self, include_inactive: bool = False) -> list[DiscountType]:
        where = "" if include_inactive else "WHERE is_active = 1"
        return [from_row(DiscountType, r) for r in self.db.query(
            f"SELECT * FROM discount_types {where} ORDER BY sort_order, name COLLATE NOCASE")]

    def payment_methods(self, include_inactive: bool = False) -> list[PaymentMethod]:
        where = "" if include_inactive else "WHERE is_active = 1"
        return [from_row(PaymentMethod, r) for r in self.db.query(
            f"SELECT * FROM payment_methods {where} ORDER BY sort_order, name COLLATE NOCASE")]

    def payment_method(self, method_id: int) -> PaymentMethod | None:
        row = self.db.one("SELECT * FROM payment_methods WHERE id = ?", (method_id,))
        return from_row(PaymentMethod, row) if row else None

    def save_catalog_row(self, table: str, row_id: int | None, values: dict[str, Any]) -> int:
        if row_id:
            self.db.update(table, row_id, values)
            return row_id
        return self.db.insert(table, values)

    def catalog_row_in_use(self, table: str, row_id: int) -> bool:
        checks = {
            "taxes": "SELECT EXISTS(SELECT 1 FROM charges WHERE tax_id = ?)",
            "charge_items": "SELECT EXISTS(SELECT 1 FROM charges WHERE charge_item_id = ?)",
            "payment_methods": "SELECT EXISTS(SELECT 1 FROM payments WHERE method_id = ?)",
            "discount_types": "SELECT 0 WHERE ? IS NOT NULL",
        }
        return bool(self.db.scalar(checks[table], (row_id,)))

    def delete_catalog_row(self, table: str, row_id: int) -> None:
        self.db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    # -- charges -------------------------------------------------------------------
    def insert_charge(self, values: dict[str, Any]) -> int:
        return self.db.insert("charges", values)

    def get_charge(self, charge_id: int) -> Charge | None:
        row = self.db.one("SELECT * FROM charges WHERE id = ?", (charge_id,))
        return from_row(Charge, row) if row else None

    def charges(self, res_id: int, include_void: bool = True) -> list[Charge]:
        where = "" if include_void else "AND c.is_void = 0"
        rows = self.db.query(
            "SELECT c.*, COALESCE(u.full_name, '') AS posted_by_name FROM charges c "
            f"LEFT JOIN users u ON u.id = c.posted_by WHERE c.reservation_id = ? {where} "
            "ORDER BY c.service_date, COALESCE(c.parent_id, c.id), c.id", (res_id,))
        return [from_row(Charge, r) for r in rows]

    def active_room_nights(self, res_id: int) -> dict[date, Charge]:
        rows = self.db.query(
            "SELECT * FROM charges WHERE reservation_id = ? AND kind = 'room' AND is_void = 0", (res_id,))
        result = {}
        for row in rows:
            charge = from_row(Charge, row)
            result[charge.service_date] = charge
        return result

    def child_ids(self, charge_id: int) -> list[int]:
        return [r[0] for r in self.db.query(
            "SELECT id FROM charges WHERE parent_id = ? AND is_void = 0", (charge_id,))]

    def void_charge(self, charge_id: int, reason: str, user_id: int | None, ts: str) -> None:
        self.db.execute("UPDATE charges SET is_void = 1, void_reason = ?, voided_by = ?, voided_at = ? "
                        "WHERE id = ? AND is_void = 0", (reason, user_id, ts, charge_id))

    def charges_total(self, res_id: int) -> int:
        return int(self.db.scalar("SELECT COALESCE(SUM(amount), 0) FROM charges "
                                  "WHERE reservation_id = ? AND is_void = 0", (res_id,), 0))

    def system_fee_ids(self, res_id: int, codes: tuple[str, ...]) -> list[int]:
        marks = ", ".join("?" for _ in codes)
        return [r[0] for r in self.db.query(
            f"SELECT c.id FROM charges c JOIN charge_items i ON i.id = c.charge_item_id "
            f"WHERE c.reservation_id = ? AND c.is_void = 0 AND i.system_code IN ({marks})", (res_id, *codes))]

    # -- payments -----------------------------------------------------------------
    def insert_payment(self, values: dict[str, Any]) -> int:
        return self.db.insert("payments", values)

    def get_payment(self, payment_id: int) -> Payment | None:
        row = self.db.one(f"{PAYMENT_SELECT} WHERE p.id = ?", (payment_id,))
        return from_row(Payment, row) if row else None

    def payments(self, res_id: int) -> list[Payment]:
        rows = self.db.query(f"{PAYMENT_SELECT} WHERE p.reservation_id = ? ORDER BY p.created_at, p.id", (res_id,))
        return [from_row(Payment, r) for r in rows]

    def paid_total(self, res_id: int) -> int:
        return int(self.db.scalar(
            "SELECT COALESCE(SUM(CASE WHEN kind = 'refund' THEN -amount ELSE amount END), 0) FROM payments "
            "WHERE reservation_id = ? AND is_void = 0", (res_id,), 0))

    def void_payment(self, payment_id: int, reason: str, user_id: int | None, ts: str) -> None:
        self.db.execute("UPDATE payments SET is_void = 1, void_reason = ?, voided_by = ?, voided_at = ? "
                        "WHERE id = ? AND is_void = 0", (reason, user_id, ts, payment_id))

    def search_payments(self, *, start: date | None = None, end: date | None = None, method_id: int | None = None,
                        kind: str = "", user_id: int | None = None, text: str = "",
                        include_void: bool = True, limit: int = 10000) -> list[Payment]:
        where, params = ["1=1"], []
        if start:
            where.append("p.created_at >= ?")
            params.append(start.isoformat())
        if end:
            where.append("p.created_at < date(?, '+1 day')")
            params.append(end.isoformat())
        if method_id:
            where.append("p.method_id = ?")
            params.append(method_id)
        if kind:
            where.append("p.kind = ?")
            params.append(kind)
        if user_id:
            where.append("p.created_by = ?")
            params.append(user_id)
        if not include_void:
            where.append("p.is_void = 0")
        if text:
            where.append("(p.receipt_no LIKE ? ESCAPE '\\' OR r.confirmation_no LIKE ? ESCAPE '\\' "
                         "OR (g.first_name || ' ' || g.last_name) LIKE ? ESCAPE '\\' OR p.reference LIKE ? ESCAPE '\\')")
            params += [like(text)] * 4
        rows = self.db.query(f"{PAYMENT_SELECT} WHERE {' AND '.join(where)} ORDER BY p.created_at DESC, p.id DESC "
                             "LIMIT ?", (*params, limit))
        return [from_row(Payment, r) for r in rows]

    # -- invoices -----------------------------------------------------------------
    def invoice_for(self, res_id: int):
        return self.db.one("SELECT * FROM invoices WHERE reservation_id = ?", (res_id,))

    def insert_invoice(self, values: dict[str, Any]) -> int:
        return self.db.insert("invoices", values)

    def list_invoices(self, start: date | None = None, end: date | None = None, text: str = ""):
        where, params = ["1=1"], []
        if start:
            where.append("i.issued_at >= ?")
            params.append(start.isoformat())
        if end:
            where.append("i.issued_at < date(?, '+1 day')")
            params.append(end.isoformat())
        if text:
            where.append("(i.invoice_no LIKE ? ESCAPE '\\' OR r.confirmation_no LIKE ? ESCAPE '\\' "
                         "OR (g.first_name || ' ' || g.last_name) LIKE ? ESCAPE '\\')")
            params += [like(text)] * 3
        return self.db.query(
            "SELECT i.*, r.confirmation_no, g.first_name || ' ' || g.last_name AS guest_name, rm.number AS room_number, "
            "r.check_in_date, r.check_out_date, COALESCE(u.full_name, '') AS issued_by_name, "
            "(SELECT COALESCE(SUM(c.amount),0) FROM charges c WHERE c.reservation_id = r.id AND c.is_void = 0) "
            "AS current_total, "
            "(SELECT COALESCE(SUM(CASE WHEN p.kind='refund' THEN -p.amount ELSE p.amount END),0) FROM payments p "
            " WHERE p.reservation_id = r.id AND p.is_void = 0) AS current_paid "
            "FROM invoices i JOIN reservations r ON r.id = i.reservation_id JOIN guests g ON g.id = r.guest_id "
            "JOIN rooms rm ON rm.id = r.room_id LEFT JOIN users u ON u.id = i.issued_by "
            f"WHERE {' AND '.join(where)} ORDER BY i.issued_at DESC, i.id DESC", params)

    def balances(self, min_balance: int = 1):
        """Reservations (not merely booked) with a balance owed of at least ``min_balance`` cents."""
        return self.db.query(
            "SELECT * FROM (SELECT r.id, r.confirmation_no, r.status, r.check_in_date, r.check_out_date, "
            "r.actual_check_out, g.id AS guest_id, g.first_name || ' ' || g.last_name AS guest_name, g.phone, g.email, "
            "rm.number AS room_number, "
            "(SELECT COALESCE(SUM(c.amount),0) FROM charges c WHERE c.reservation_id = r.id AND c.is_void = 0) AS total, "
            "(SELECT COALESCE(SUM(CASE WHEN p.kind='refund' THEN -p.amount ELSE p.amount END),0) FROM payments p "
            " WHERE p.reservation_id = r.id AND p.is_void = 0) AS paid "
            "FROM reservations r JOIN guests g ON g.id = r.guest_id JOIN rooms rm ON rm.id = r.room_id "
            "WHERE r.status <> 'confirmed') WHERE total - paid >= ? ORDER BY status = 'checked_in', check_out_date",
            (min_balance,))

    def credits(self):
        """Closed reservations where the guest paid more than charged (refund due)."""
        return self.db.query(
            "SELECT * FROM (SELECT r.id, r.confirmation_no, r.status, g.first_name || ' ' || g.last_name AS guest_name, "
            "rm.number AS room_number, "
            "(SELECT COALESCE(SUM(c.amount),0) FROM charges c WHERE c.reservation_id = r.id AND c.is_void = 0) AS total, "
            "(SELECT COALESCE(SUM(CASE WHEN p.kind='refund' THEN -p.amount ELSE p.amount END),0) FROM payments p "
            " WHERE p.reservation_id = r.id AND p.is_void = 0) AS paid "
            "FROM reservations r JOIN guests g ON g.id = r.guest_id JOIN rooms rm ON rm.id = r.room_id "
            "WHERE r.status IN ('checked_out', 'cancelled', 'no_show')) WHERE paid - total > 0")
