"""Schema migrations.

The schema version is tracked with SQLite's ``PRAGMA user_version``. Each
migration runs inside a transaction; if any statement fails the database is
left untouched at its previous version. Before upgrading an existing database
an automatic safety backup is written next to it.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime
from typing import Callable

from motelmg.core.errors import DatabaseError
from motelmg.data.database import Database
from motelmg.data.schema import SCHEMA_V1
from motelmg.data.seed import seed_reference_data

log = logging.getLogger(__name__)


def _v1(db: Database) -> None:
    for statement in _split_sql(SCHEMA_V1):
        db.execute(statement)
    seed_reference_data(db)


MIGRATIONS: list[tuple[int, str, Callable[[Database], None]]] = [
    (1, "Initial schema", _v1),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def _split_sql(script: str) -> list[str]:
    """Split a SQL script into statements (trigger bodies contain ';')."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buffer.append(line)
        candidate = "\n".join(buffer)
        if stripped.endswith(";") and sqlite3.complete_statement(candidate):
            statements.append(candidate.strip())
            buffer = []
    if buffer and "".join(buffer).strip():
        statements.append("\n".join(buffer).strip())
    return statements


def current_version(db: Database) -> int:
    return int(db.scalar("PRAGMA user_version", default=0))


def migrate(db: Database) -> int:
    """Bring the database up to :data:`LATEST_VERSION`. Returns the new version."""
    version = current_version(db)
    if version > LATEST_VERSION:
        raise DatabaseError(
            "This database was created by a newer version of MotelMG. "
            "Please install the latest version of the application.")
    if version == LATEST_VERSION:
        return version
    if version > 0 and db.path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety = db.path.with_name(f"{db.path.stem}-pre-v{LATEST_VERSION}-{stamp}.db")
        db.checkpoint()
        shutil.copy2(db.path, safety)
        log.info("Pre-migration backup written to %s", safety)
    for number, description, fn in MIGRATIONS:
        if number <= version:
            continue
        log.info("Applying migration %s: %s", number, description)
        with db.transaction():
            fn(db)
            db.execute(f"PRAGMA user_version = {int(number)}")
    return current_version(db)
