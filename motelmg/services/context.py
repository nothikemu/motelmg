"""Application context: wires the database, repositories and services
together and tracks the signed-in user session."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from motelmg.core.dates import Clock
from motelmg.core.errors import PermissionDenied
from motelmg.core.permissions import ADMIN_ROLE, PERMISSION_LABELS
from motelmg.data import repositories as repos
from motelmg.data.database import Database
from motelmg.data.migrations import migrate

log = logging.getLogger(__name__)


@dataclass
class Session:
    user_id: int
    username: str
    full_name: str
    role_id: int
    role_name: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    must_change_password: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role_name == ADMIN_ROLE

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def has_any(self, *permissions: str) -> bool:
        return any(p in self.permissions for p in permissions)


class EventBus:
    """Tiny synchronous publish/subscribe hub. Topics are entity names such as
    ``"reservations"`` or ``"rooms"``; the UI refreshes views on events."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[str], None]]] = defaultdict(list)

    def subscribe(self, topic: str, callback: Callable[[str], None]) -> None:
        self._subscribers[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[str], None]) -> None:
        callbacks = self._subscribers.get(topic, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def unsubscribe_all(self) -> None:
        self._subscribers.clear()

    def emit(self, *topics: str) -> None:
        for topic in (*topics, "*"):
            for callback in list(self._subscribers.get(topic, [])):
                try:
                    callback(topic if topic != "*" else ",".join(topics))
                except Exception:  # pragma: no cover - never let a listener break a service
                    log.exception("Event listener failed for %s", topic)


class AppContext:
    def __init__(self, db_path: Path | str, clock: Clock | None = None):
        self.db = Database(db_path)
        self.clock = clock or Clock()
        self.session: Session | None = None
        self.events = EventBus()
        migrate(self.db)
        self._build()

    def _build(self) -> None:
        from motelmg.services.alerts import AlertService
        from motelmg.services.audit import AuditService
        from motelmg.services.auth import AuthService
        from motelmg.services.backups import BackupService
        from motelmg.services.billing import BillingService
        from motelmg.services.catalog import CatalogService
        from motelmg.services.dashboard import DashboardService
        from motelmg.services.guests import GuestService
        from motelmg.services.housekeeping import HousekeepingService
        from motelmg.services.maintenance import MaintenanceService
        from motelmg.services.notes import NoteService
        from motelmg.services.reports import ReportService
        from motelmg.services.reservations import ReservationService
        from motelmg.services.rooms import RoomService
        from motelmg.services.search import SearchService
        from motelmg.services.settings import SettingsService
        from motelmg.services.users import UserService

        db = self.db
        self.repo_settings = repos.SettingsRepository(db)
        self.repo_audit = repos.AuditRepository(db)
        self.repo_staff = repos.StaffRepository(db)
        self.repo_rooms = repos.RoomRepository(db)
        self.repo_guests = repos.GuestRepository(db)
        self.repo_res = repos.ReservationRepository(db)
        self.repo_folio = repos.FolioRepository(db)
        self.repo_hk = repos.HousekeepingRepository(db)
        self.repo_maint = repos.MaintenanceRepository(db)
        self.repo_notes = repos.NoteRepository(db)
        self.repo_notify = repos.NotificationRepository(db)

        self.settings = SettingsService(self)
        self.audit = AuditService(self)
        self.auth = AuthService(self)
        self.users = UserService(self)
        self.catalog = CatalogService(self)
        self.rooms = RoomService(self)
        self.guests = GuestService(self)
        self.notes = NoteService(self)
        self.billing = BillingService(self)
        self.reservations = ReservationService(self)
        self.housekeeping = HousekeepingService(self)
        self.maintenance = MaintenanceService(self)
        self.alerts = AlertService(self)
        self.reports = ReportService(self)
        self.search = SearchService(self)
        self.dashboard = DashboardService(self)
        self.backups = BackupService(self)

    def reopen(self) -> None:
        """Reconnect after the database file was replaced (restore)."""
        self.db.close()
        migrate(self.db)
        self.settings.invalidate()
        self.billing.invalidate_cache()

    def close(self) -> None:
        self.db.close()

    # -- session helpers --------------------------------------------------------
    @property
    def user_id(self) -> int | None:
        return self.session.user_id if self.session else None

    def require(self, *permissions: str) -> None:
        """Raise ``PermissionDenied`` unless the current user holds *all* permissions."""
        if self.session is None:
            raise PermissionDenied("You must be signed in to do that.")
        for perm in permissions:
            if not self.session.has(perm):
                raise PermissionDenied(
                    f"Your role ({self.session.role_name}) does not allow: "
                    f"{PERMISSION_LABELS.get(perm, perm)}. Ask a manager for help.")

    def can(self, permission: str) -> bool:
        return bool(self.session and self.session.has(permission))

    def now_str(self) -> str:
        return self.clock.now().strftime("%Y-%m-%d %H:%M:%S")
