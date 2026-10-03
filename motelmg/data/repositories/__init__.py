"""Repositories encapsulate all SQL used by the business services."""

from motelmg.data.repositories.folio import FolioRepository
from motelmg.data.repositories.guests import GuestRepository
from motelmg.data.repositories.housekeeping import HousekeepingRepository
from motelmg.data.repositories.maintenance import MaintenanceRepository
from motelmg.data.repositories.misc import (AuditRepository, NoteRepository, NotificationRepository,
                                            SettingsRepository)
from motelmg.data.repositories.reservations import ReservationRepository
from motelmg.data.repositories.rooms import RoomRepository
from motelmg.data.repositories.staff import StaffRepository

__all__ = [
    "AuditRepository", "FolioRepository", "GuestRepository", "HousekeepingRepository",
    "MaintenanceRepository", "NoteRepository", "NotificationRepository", "ReservationRepository",
    "RoomRepository", "SettingsRepository", "StaffRepository",
]
