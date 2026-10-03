from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from motelmg.data.repositories.base import Repository, like
from motelmg.models import AuditEntry, Note, from_row


class SettingsRepository(Repository):
    def all(self) -> dict[str, Any]:
        result = {}
        for row in self.db.query("SELECT key, value FROM settings"):
            try:
                result[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                result[row["key"]] = row["value"]
        return result

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)))


class AuditRepository(Repository):
    def insert(self, ts: str, user_id: int | None, username: str, action: str, entity_type: str,
               entity_id: int | None, summary: str, details: str) -> None:
        self.db.execute(
            "INSERT INTO audit_log(ts, user_id, username, action, entity_type, entity_id, summary, details) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, user_id, username, action, entity_type, entity_id, summary, details))

    def search(self, *, start: date | None = None, end: date | None = None, user_id: int | None = None,
               action_prefix: str = "", text: str = "", entity_type: str = "", entity_id: int | None = None,
               limit: int = 2000) -> list[AuditEntry]:
        where, params = ["1=1"], []
        if start:
            where.append("ts >= ?")
            params.append(start.isoformat())
        if end:
            where.append("ts < date(?, '+1 day')")
            params.append(end.isoformat())
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        if action_prefix:
            where.append("action LIKE ?")
            params.append(action_prefix + "%")
        if entity_type:
            where.append("entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            where.append("entity_id = ?")
            params.append(entity_id)
        if text:
            where.append("(summary LIKE ? ESCAPE '\\' OR username LIKE ? ESCAPE '\\' OR details LIKE ? ESCAPE '\\')")
            params += [like(text)] * 3
        rows = self.db.query(
            f"SELECT * FROM audit_log WHERE {' AND '.join(where)} ORDER BY ts DESC, id DESC LIMIT ?",
            (*params, limit))
        return [from_row(AuditEntry, r) for r in rows]

    def actions(self) -> list[str]:
        return [r[0] for r in self.db.query("SELECT DISTINCT action FROM audit_log ORDER BY action")]


class NoteRepository(Repository):
    def add(self, *, body: str, important: bool, user_id: int | None, ts: str, guest_id: int | None = None,
            reservation_id: int | None = None, room_id: int | None = None) -> int:
        return self.db.insert("notes", {
            "guest_id": guest_id, "reservation_id": reservation_id, "room_id": room_id, "body": body,
            "is_important": int(important), "created_by": user_id, "created_at": ts})

    def list(self, *, guest_id: int | None = None, reservation_id: int | None = None,
             room_id: int | None = None) -> list[Note]:
        if guest_id is not None:
            col, value = "guest_id", guest_id
        elif reservation_id is not None:
            col, value = "reservation_id", reservation_id
        else:
            col, value = "room_id", room_id
        rows = self.db.query(
            f"SELECT n.*, COALESCE(u.full_name, 'System') AS author FROM notes n "
            f"LEFT JOIN users u ON u.id = n.created_by WHERE n.{col} = ? "
            f"ORDER BY n.is_important DESC, n.created_at DESC, n.id DESC", (value,))
        return [from_row(Note, r) for r in rows]

    def get(self, note_id: int):
        return self.db.one("SELECT * FROM notes WHERE id = ?", (note_id,))

    def delete(self, note_id: int) -> None:
        self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def important_for_guest(self, guest_id: int) -> list[Note]:
        rows = self.db.query(
            "SELECT n.*, COALESCE(u.full_name, 'System') AS author FROM notes n "
            "LEFT JOIN users u ON u.id = n.created_by WHERE n.guest_id = ? AND n.is_important = 1 "
            "ORDER BY n.created_at DESC", (guest_id,))
        return [from_row(Note, r) for r in rows]


class NotificationRepository(Repository):
    def add(self, ts: datetime, level: str, category: str, title: str, message: str) -> int:
        return self.db.insert("notifications", {
            "ts": ts.strftime("%Y-%m-%d %H:%M:%S"), "level": level, "category": category,
            "title": title, "message": message})

    def recent(self, limit: int = 50, unread_only: bool = False):
        where = "WHERE is_read = 0" if unread_only else ""
        return self.db.query(f"SELECT * FROM notifications {where} ORDER BY ts DESC, id DESC LIMIT ?", (limit,))

    def mark_read(self, notification_id: int | None = None) -> None:
        if notification_id is None:
            self.db.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
        else:
            self.db.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))

    def dismissed_keys(self, user_id: int, day: date) -> set[str]:
        return {r[0] for r in self.db.query(
            "SELECT alert_key FROM alert_dismissals WHERE user_id = ? AND dismissed_on = ?",
            (user_id, day.isoformat()))}

    def dismiss(self, key: str, user_id: int, day: date) -> None:
        self.db.execute("INSERT OR IGNORE INTO alert_dismissals(alert_key, user_id, dismissed_on) VALUES (?,?,?)",
                        (key, user_id, day.isoformat()))

    def clear_dismissals(self, user_id: int, day: date) -> None:
        self.db.execute("DELETE FROM alert_dismissals WHERE user_id = ? AND dismissed_on = ?",
                        (user_id, day.isoformat()))

    def purge_old_dismissals(self, before: date) -> None:
        self.db.execute("DELETE FROM alert_dismissals WHERE dismissed_on < ?", (before.isoformat(),))
