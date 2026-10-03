"""Permission catalog and the default role definitions.

Permissions are simple dotted strings. Roles are stored in the database and
reference these strings, so administrators can create custom roles and change
which permissions a role holds from the Staff screen.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    code: str
    group: str
    label: str
    description: str = ""


ALL_PERMISSIONS: list[Permission] = [
    Permission("dashboard.view", "General", "View dashboard"),
    Permission("guests.view", "Guests", "View guests"),
    Permission("guests.edit", "Guests", "Create and edit guests"),
    Permission("guests.delete", "Guests", "Delete guests"),
    Permission("reservations.view", "Reservations", "View reservations and calendar"),
    Permission("reservations.create", "Reservations", "Create reservations and walk-ins"),
    Permission("reservations.edit", "Reservations", "Modify reservations"),
    Permission("reservations.cancel", "Reservations", "Cancel reservations / mark no-show"),
    Permission("reservations.checkin", "Reservations", "Check guests in"),
    Permission("reservations.checkout", "Reservations", "Check guests out"),
    Permission("reservations.transfer", "Reservations", "Transfer guests between rooms"),
    Permission("reservations.override_rate", "Reservations", "Override room rates",
               "Set a nightly rate different from the standard rate."),
    Permission("billing.view", "Billing", "View folios and transactions"),
    Permission("billing.charge", "Billing", "Post charges"),
    Permission("billing.payment", "Billing", "Take payments and deposits"),
    Permission("billing.discount", "Billing", "Apply discounts"),
    Permission("billing.refund", "Billing", "Issue refunds"),
    Permission("billing.void", "Billing", "Void charges and payments"),
    Permission("billing.checkout_balance", "Billing", "Check out with unpaid balance",
               "Allow departure with an outstanding balance (direct bill)."),
    Permission("rooms.view", "Rooms", "View room board"),
    Permission("rooms.status", "Rooms", "Change room service status",
               "Put rooms out of service and return them to service."),
    Permission("rooms.manage", "Rooms", "Manage rooms, room types and rates"),
    Permission("housekeeping.view", "Housekeeping", "View housekeeping"),
    Permission("housekeeping.work", "Housekeeping", "Perform cleaning tasks",
               "Start and complete assigned cleaning tasks."),
    Permission("housekeeping.manage", "Housekeeping", "Assign and manage tasks"),
    Permission("housekeeping.inspect", "Housekeeping", "Inspect rooms"),
    Permission("maintenance.view", "Maintenance", "View maintenance tickets"),
    Permission("maintenance.report", "Maintenance", "Report maintenance issues"),
    Permission("maintenance.manage", "Maintenance", "Manage and resolve tickets"),
    Permission("reports.view", "Reports", "View operational reports"),
    Permission("reports.financial", "Reports", "View financial reports"),
    Permission("staff.manage", "Administration", "Manage staff accounts and roles"),
    Permission("audit.view", "Administration", "View audit log"),
    Permission("settings.manage", "Administration", "Change system settings"),
    Permission("backup.manage", "Administration", "Back up and restore database"),
]

PERMISSION_CODES = frozenset(p.code for p in ALL_PERMISSIONS)
PERMISSION_LABELS = {p.code: p.label for p in ALL_PERMISSIONS}

ADMIN_ROLE = "Administrator"


def _all() -> set[str]:
    return set(PERMISSION_CODES)


DEFAULT_ROLES: dict[str, tuple[str, set[str]]] = {
    ADMIN_ROLE: ("Full access to every feature, settings and staff accounts.", _all()),
    "Manager": (
        "Runs daily operations; can override rates, refund, void and see financial reports.",
        _all() - {"settings.manage", "backup.manage"},
    ),
    "Front Desk": (
        "Reservations, check-in/out, guest profiles and payments.",
        {
            "dashboard.view", "guests.view", "guests.edit",
            "reservations.view", "reservations.create", "reservations.edit", "reservations.cancel",
            "reservations.checkin", "reservations.checkout", "reservations.transfer",
            "billing.view", "billing.charge", "billing.payment",
            "rooms.view", "housekeeping.view", "maintenance.view", "maintenance.report",
            "reports.view",
        },
    ),
    "Housekeeping": (
        "Sees the housekeeping board and completes cleaning tasks.",
        {"housekeeping.view", "housekeeping.work", "rooms.view", "maintenance.view", "maintenance.report"},
    ),
    "Maintenance": (
        "Handles maintenance tickets and room service status.",
        {"maintenance.view", "maintenance.report", "maintenance.manage", "rooms.view", "rooms.status",
         "housekeeping.view"},
    ),
}
