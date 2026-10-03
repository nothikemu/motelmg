"""Backup scheduling and restore on top of :mod:`motelmg.data.backup`."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from motelmg.core.dates import parse_datetime
from motelmg.data import backup as store

log = logging.getLogger(__name__)


class BackupService:
    def __init__(self, ctx):
        self.ctx = ctx

    def directory(self) -> Path:
        return self.ctx.settings.backup_dir()

    def list(self) -> list[store.BackupInfo]:
        return store.list_backups(self.directory())

    def backup_now(self, label: str = "manual", *, require_permission: bool = True) -> Path:
        if require_permission:
            self.ctx.require("backup.manage")
        path = store.create_backup(self.ctx.db, self.directory(), label)
        self._mark_done()
        if label not in ("auto", "on exit"):
            with self.ctx.db.transaction():
                self.ctx.audit.log("backup.create", "backup", None, f"Database backed up to {path.name}")
        store.prune_backups(self.directory(), self.ctx.settings.get_int("backup.keep"))
        self.ctx.events.emit("backups")
        return path

    def _mark_done(self) -> None:
        self.ctx.settings.update({"backup.last_at": self.ctx.now_str()}, audit=False, require_permission=False)

    def is_due(self) -> bool:
        settings = self.ctx.settings
        if not settings.get_bool("backup.auto_enabled"):
            return False
        frequency = settings.get_str("backup.frequency")
        if frequency == "on_exit":
            return False
        last = parse_datetime(settings.get_str("backup.last_at"))
        if last is None:
            return True
        interval = timedelta(days=7 if frequency == "weekly" else 1)
        return self.ctx.clock.now() - last >= interval

    def auto_backup_if_due(self) -> Path | None:
        if not self.is_due():
            return None
        try:
            return self.backup_now("auto", require_permission=False)
        except Exception as exc:  # report but never crash the app over a backup
            log.exception("Automatic backup failed")
            self.ctx.alerts.notify("Automatic backup failed", str(exc), level="warning")
            return None

    def backup_on_exit(self) -> Path | None:
        settings = self.ctx.settings
        if settings.get_bool("backup.auto_enabled") and settings.get_str("backup.frequency") == "on_exit":
            try:
                return self.backup_now("on exit", require_permission=False)
            except Exception:
                log.exception("Backup on exit failed")
        return None

    def inspect(self, path: Path) -> store.BackupDetails:
        return store.inspect_backup(path)

    def restore(self, path: Path) -> Path:
        """Restore ``path`` over the live database. Returns the safety backup path.
        The caller must sign out and rebuild the UI afterwards."""
        self.ctx.require("backup.manage")
        user = self.ctx.session.username if self.ctx.session else "system"
        safety = store.restore_backup(self.ctx.db, path, self.directory())
        self.ctx.reopen()
        with self.ctx.db.transaction():
            self.ctx.repo_audit.insert(self.ctx.now_str(), None, user, "backup.restore", "backup", None,
                                       f"Database restored from {Path(path).name} by {user}",
                                       f"safety copy: {safety}")
            self.ctx.repo_notify.add(self.ctx.clock.now(), "info", "system", "Database restored",
                                     f"Restored from {Path(path).name}. A copy of the previous data was saved as "
                                     f"{safety.name}.")
        self.ctx.session = None
        self.ctx.events.emit("*")
        return safety
