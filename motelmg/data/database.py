"""SQLite database access.

``Database`` owns one connection per thread (SQLite connections must not be
shared between threads), enables foreign keys / WAL journaling, and provides
a re-entrant :meth:`transaction` context manager. Nested transactions use
SAVEPOINTs so a service method can call another service method that also
opens a transaction.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from motelmg.core.errors import ConflictError, DatabaseError, ValidationError

log = logging.getLogger(__name__)

Params = Sequence[Any] | dict[str, Any]


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._local = threading.local()
        self._all_connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    # -- connection management -------------------------------------------
    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=15, isolation_level=None,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:  # pragma: no cover - e.g. network drives
            log.warning("WAL journal mode unavailable; using default journal")
        conn.execute("PRAGMA synchronous = NORMAL")
        with self._lock:
            self._all_connections.append(conn)
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open()
            self._local.conn = conn
            self._local.depth = 0
        return conn

    def close(self) -> None:
        """Close every connection opened by this object (all threads)."""
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except sqlite3.Error:  # pragma: no cover
                    pass
            self._all_connections.clear()
        self._local = threading.local()

    def checkpoint(self) -> None:
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:  # pragma: no cover
            log.exception("WAL checkpoint failed")

    # -- transactions --------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.conn
        depth = getattr(self._local, "depth", 0)
        name = f"sp_{depth}"
        try:
            if depth == 0:
                conn.execute("BEGIN IMMEDIATE")
            else:
                conn.execute(f"SAVEPOINT {name}")
        except sqlite3.Error as exc:
            raise translate_error(exc) from exc
        self._local.depth = depth + 1
        try:
            yield conn
        except BaseException:
            self._local.depth = depth
            try:
                if depth == 0:
                    conn.execute("ROLLBACK")
                else:
                    conn.execute(f"ROLLBACK TO {name}")
                    conn.execute(f"RELEASE {name}")
            except sqlite3.Error:  # pragma: no cover
                log.exception("Rollback failed")
            raise
        else:
            self._local.depth = depth
            try:
                if depth == 0:
                    conn.execute("COMMIT")
                else:
                    conn.execute(f"RELEASE {name}")
            except sqlite3.Error as exc:
                if depth == 0 and conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise translate_error(exc) from exc

    @property
    def in_transaction(self) -> bool:
        return getattr(self._local, "depth", 0) > 0

    # -- query helpers -------------------------------------------------------
    def execute(self, sql: str, params: Params = ()) -> sqlite3.Cursor:
        try:
            return self.conn.execute(sql, params)
        except sqlite3.Error as exc:
            raise translate_error(exc) from exc

    def executemany(self, sql: str, seq: Iterable[Params]) -> sqlite3.Cursor:
        try:
            return self.conn.executemany(sql, seq)
        except sqlite3.Error as exc:
            raise translate_error(exc) from exc

    def query(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def one(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Params = (), default: Any = None) -> Any:
        row = self.execute(sql, params).fetchone()
        if row is None or row[0] is None:
            return default
        return row[0]

    def insert(self, table: str, values: dict[str, Any]) -> int:
        cols = ", ".join(values)
        marks = ", ".join(f":{k}" for k in values)
        cur = self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", values)
        return int(cur.lastrowid)

    def update(self, table: str, row_id: int, values: dict[str, Any]) -> None:
        if not values:
            return
        sets = ", ".join(f"{k} = :{k}" for k in values)
        params = dict(values)
        params["__id"] = row_id
        self.execute(f"UPDATE {table} SET {sets} WHERE id = :__id", params)

    def next_counter(self, name: str) -> int:
        """Atomically increment and return a named counter (call in a transaction)."""
        with self.transaction():
            self.execute("INSERT OR IGNORE INTO counters(name, value) VALUES (?, 0)", (name,))
            self.execute("UPDATE counters SET value = value + 1 WHERE name = ?", (name,))
            return int(self.scalar("SELECT value FROM counters WHERE name = ?", (name,)))

    def integrity_check(self) -> str:
        return str(self.scalar("PRAGMA integrity_check", default="unknown"))


_UNIQUE_MESSAGES = {
    "rooms.number": ("A room with this number already exists.", "number"),
    "room_types.name": ("A room type with this name already exists.", "name"),
    "room_types.code": ("A room type with this code already exists.", "code"),
    "users.username": ("This username is already taken.", "username"),
    "roles.name": ("A role with this name already exists.", "name"),
    "payment_methods.name": ("A payment method with this name already exists.", "name"),
    "taxes.name": ("A tax with this name already exists.", "name"),
    "charge_items.name": ("A charge item with this name already exists.", "name"),
    "discount_types.name": ("A discount with this name already exists.", "name"),
    "guests.id_type, guests.id_number": ("Another guest already has this ID document on file.", "id_number"),
    "charges.reservation_id, charges.service_date": ("This night has already been charged.", None),
    "housekeeping_tasks.room_id, housekeeping_tasks.task_type":
        ("This room already has an open task of that type.", None),
    "reservations.room_id": ("This room already has a guest checked in.", None),
}


def translate_error(exc: sqlite3.Error) -> Exception:
    """Map low level SQLite errors to user facing application errors."""
    message = str(exc)
    if isinstance(exc, sqlite3.IntegrityError):
        if "ROOM_DOUBLE_BOOKED" in message:
            return ConflictError("This room is already booked for some of the selected nights.")
        if "ROOM_OCCUPIED" in message:
            return ConflictError("This room already has a guest checked in.")
        match = re.search(r"UNIQUE constraint failed: (.+)$", message)
        if match:
            key = match.group(1).strip()
            text, field = _UNIQUE_MESSAGES.get(key, ("This record already exists (duplicate).", None))
            return ValidationError(text, field=field) if field else ConflictError(text)
        if "FOREIGN KEY" in message:
            return ConflictError("This record is linked to other records and cannot be changed this way.")
        if "CHECK constraint failed" in message:
            return ValidationError("One of the values is outside the allowed range.")
        if "NOT NULL" in message:
            return ValidationError("A required value is missing.")
        return ConflictError("The change conflicts with existing data.", details=message)
    if isinstance(exc, sqlite3.OperationalError) and "locked" in message:
        return DatabaseError("The database is busy. Please try again in a moment.", details=message)
    if isinstance(exc, sqlite3.DatabaseError) and ("malformed" in message or "not a database" in message):
        return DatabaseError("The database file appears to be damaged. Restore from a backup in Settings.",
                             details=message)
    return DatabaseError("A database error occurred.", details=message)
