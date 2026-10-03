"""Online backups and restore of the SQLite database file."""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from motelmg.core.errors import DatabaseError, ValidationError
from motelmg.data.database import Database
from motelmg.data.migrations import LATEST_VERSION

log = logging.getLogger(__name__)

BACKUP_PATTERN = "motelmg-backup-*.db"
REQUIRED_TABLES = {"settings", "users", "roles", "rooms", "room_types", "guests", "reservations",
                   "charges", "payments"}


@dataclass
class BackupInfo:
    path: Path
    size: int
    created: datetime
    label: str = ""


@dataclass
class BackupDetails:
    path: Path
    schema_version: int
    property_name: str
    guests: int
    reservations: int
    rooms: int


def _label_slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug[:30]


def create_backup(db: Database, dest_dir: Path, label: str = "") -> Path:
    dest_dir = Path(dest_dir)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatabaseError(f"Cannot create backup folder {dest_dir}: {exc.strerror}") from exc
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _label_slug(label)
    name = f"motelmg-backup-{stamp}{'-' + slug if slug else ''}.db"
    target = dest_dir / name
    counter = 1
    while target.exists():
        target = dest_dir / name.replace(".db", f"-{counter}.db")
        counter += 1
    tmp = target.with_suffix(".tmp")
    try:
        dest = sqlite3.connect(str(tmp))
        try:
            db.conn.backup(dest)
        finally:
            dest.close()
        tmp.replace(target)
    except (sqlite3.Error, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise DatabaseError(f"Backup failed: {exc}") from exc
    log.info("Backup written to %s", target)
    return target


def list_backups(directory: Path) -> list[BackupInfo]:
    directory = Path(directory)
    if not directory.exists():
        return []
    result = []
    for path in directory.glob(BACKUP_PATTERN):
        try:
            stat = path.stat()
        except OSError:
            continue
        match = re.match(r"motelmg-backup-(\d{8}-\d{6})(?:-(.+))?\.db$", path.name)
        created = datetime.fromtimestamp(stat.st_mtime)
        label = ""
        if match:
            try:
                created = datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
            except ValueError:
                pass
            label = (match.group(2) or "").replace("-", " ")
        result.append(BackupInfo(path=path, size=stat.st_size, created=created, label=label))
    result.sort(key=lambda b: b.created, reverse=True)
    return result


def prune_backups(directory: Path, keep: int) -> int:
    """Delete automatic backups beyond the newest ``keep``. Returns count removed."""
    if keep <= 0:
        return 0
    removed = 0
    autos = [b for b in list_backups(directory) if b.label in ("auto", "on exit")]
    for info in autos[keep:]:
        try:
            info.path.unlink()
            removed += 1
        except OSError:
            log.warning("Could not remove old backup %s", info.path)
    return removed


def inspect_backup(path: Path) -> BackupDetails:
    """Validate that ``path`` is a usable MotelMG database and summarise it."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise ValidationError("The selected backup file does not exist.")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValidationError(f"The file could not be opened: {exc}") from exc
    try:
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()[0]
        except sqlite3.DatabaseError:
            raise ValidationError("The selected file is not a valid MotelMG backup.") from None
        if check != "ok":
            raise ValidationError("The backup file is damaged and cannot be restored.")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES.issubset(tables):
            raise ValidationError("The selected file is not a MotelMG database.")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > LATEST_VERSION:
            raise ValidationError("This backup was made by a newer version of MotelMG.")
        row = conn.execute("SELECT value FROM settings WHERE key='property.name'").fetchone()
        name = json.loads(row[0]) if row else ""
        return BackupDetails(
            path=path, schema_version=version, property_name=str(name),
            guests=conn.execute("SELECT COUNT(*) FROM guests").fetchone()[0],
            reservations=conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0],
            rooms=conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0],
        )
    finally:
        conn.close()


def restore_backup(db: Database, source: Path, safety_dir: Path) -> Path:
    """Replace the live database with ``source``.

    A safety backup of the current database is written first and returned so
    the operation can be undone. All connections of ``db`` are closed; callers
    must re-run migrations and rebuild any state afterwards.
    """
    source = Path(source)
    inspect_backup(source)
    safety = create_backup(db, safety_dir, "before restore")
    db.checkpoint()
    db.close()
    live = db.path
    staging = live.with_suffix(".restore-tmp")
    try:
        shutil.copy2(source, staging)
        for suffix in ("-wal", "-shm"):
            Path(str(live) + suffix).unlink(missing_ok=True)
        staging.replace(live)
    except OSError as exc:
        staging.unlink(missing_ok=True)
        raise DatabaseError(f"Restore failed: {exc}. Your data was not changed.") from exc
    log.info("Database restored from %s (safety copy %s)", source, safety)
    return safety
