"""Status values used across the application with human readable labels.

Each status is a plain string constant (stored as-is in the database); the
``LABELS`` dictionaries provide display names and ``TONES`` map a status to a
semantic colour used by the UI badges.
"""

from __future__ import annotations


class ReservationStatus:
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"

    ACTIVE = (CONFIRMED, CHECKED_IN)  # hold inventory
    ALL = (CONFIRMED, CHECKED_IN, CHECKED_OUT, CANCELLED, NO_SHOW)
    LABELS = {
        CONFIRMED: "Confirmed",
        CHECKED_IN: "In house",
        CHECKED_OUT: "Checked out",
        CANCELLED: "Cancelled",
        NO_SHOW: "No-show",
    }
    TONES = {
        CONFIRMED: "purple",
        CHECKED_IN: "blue",
        CHECKED_OUT: "gray",
        CANCELLED: "red",
        NO_SHOW: "orange",
    }


class ReservationSource:
    WALK_IN = "walk_in"
    PHONE = "phone"
    EMAIL = "email"
    WEBSITE = "website"
    OTA = "ota"
    CORPORATE = "corporate"
    OTHER = "other"
    LABELS = {
        PHONE: "Phone",
        WALK_IN: "Walk-in",
        EMAIL: "Email",
        WEBSITE: "Website",
        OTA: "Online travel agency",
        CORPORATE: "Corporate",
        OTHER: "Other",
    }


class HKStatus:
    DIRTY = "dirty"
    CLEANING = "cleaning"
    CLEAN = "clean"
    INSPECTED = "inspected"
    ALL = (DIRTY, CLEANING, CLEAN, INSPECTED)
    LABELS = {DIRTY: "Dirty", CLEANING: "Cleaning", CLEAN: "Clean", INSPECTED: "Inspected"}
    TONES = {DIRTY: "amber", CLEANING: "cyan", CLEAN: "green", INSPECTED: "teal"}


class ServiceStatus:
    IN_SERVICE = "in_service"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"
    ALL = (IN_SERVICE, MAINTENANCE, OUT_OF_SERVICE)
    LABELS = {IN_SERVICE: "In service", MAINTENANCE: "Maintenance", OUT_OF_SERVICE: "Out of service"}
    TONES = {IN_SERVICE: "green", MAINTENANCE: "orange", OUT_OF_SERVICE: "slate"}


class Occupancy:
    """Derived (not stored) occupancy state of a room for a given day."""

    VACANT = "vacant"
    OCCUPIED = "occupied"
    RESERVED = "reserved"  # arrival expected today
    LABELS = {VACANT: "Vacant", OCCUPIED: "Occupied", RESERVED: "Arrival"}


class RoomState:
    """Single combined state shown on the room board."""

    AVAILABLE = "available"
    VACANT_DIRTY = "vacant_dirty"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    DUE_OUT = "due_out"
    OVERDUE = "overdue"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"
    LABELS = {
        AVAILABLE: "Vacant · Ready",
        VACANT_DIRTY: "Vacant · Needs cleaning",
        OCCUPIED: "Occupied",
        RESERVED: "Arriving today",
        DUE_OUT: "Due out",
        OVERDUE: "Overdue check-out",
        MAINTENANCE: "Maintenance",
        OUT_OF_SERVICE: "Out of service",
    }
    TONES = {
        AVAILABLE: "green",
        VACANT_DIRTY: "amber",
        OCCUPIED: "blue",
        RESERVED: "purple",
        DUE_OUT: "indigo",
        OVERDUE: "red",
        MAINTENANCE: "orange",
        OUT_OF_SERVICE: "slate",
    }


class ChargeKind:
    ROOM = "room"
    TAX = "tax"
    FEE = "fee"
    EXTRA = "extra"
    DISCOUNT = "discount"
    ADJUSTMENT = "adjustment"
    LABELS = {
        ROOM: "Room", TAX: "Tax", FEE: "Fee", EXTRA: "Extra", DISCOUNT: "Discount", ADJUSTMENT: "Adjustment",
    }


class PaymentKind:
    PAYMENT = "payment"
    DEPOSIT = "deposit"
    REFUND = "refund"
    LABELS = {PAYMENT: "Payment", DEPOSIT: "Deposit", REFUND: "Refund"}
    TONES = {PAYMENT: "green", DEPOSIT: "teal", REFUND: "red"}


class TaskType:
    CHECKOUT = "checkout"
    STAYOVER = "stayover"
    DEEP_CLEAN = "deep_clean"
    TOUCH_UP = "touch_up"
    INSPECTION = "inspection"
    LABELS = {
        CHECKOUT: "Departure clean",
        STAYOVER: "Stayover service",
        DEEP_CLEAN: "Deep clean",
        TOUCH_UP: "Touch-up",
        INSPECTION: "Inspection",
    }
    CLEANING = (CHECKOUT, DEEP_CLEAN, TOUCH_UP)  # makes a vacant room clean when completed


class TaskStatus:
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INSPECTED = "inspected"
    CANCELLED = "cancelled"
    OPEN = (PENDING, IN_PROGRESS)
    LABELS = {
        PENDING: "Pending",
        IN_PROGRESS: "In progress",
        COMPLETED: "Completed",
        INSPECTED: "Inspected",
        CANCELLED: "Cancelled",
    }
    TONES = {PENDING: "amber", IN_PROGRESS: "cyan", COMPLETED: "green", INSPECTED: "teal", CANCELLED: "gray"}


class Priority:
    URGENT = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    LABELS = {URGENT: "Urgent", HIGH: "High", NORMAL: "Normal", LOW: "Low"}
    TONES = {URGENT: "red", HIGH: "orange", NORMAL: "blue", LOW: "gray"}


class TicketStatus:
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    ACTIVE = (OPEN, IN_PROGRESS, ON_HOLD)
    LABELS = {OPEN: "Open", IN_PROGRESS: "In progress", ON_HOLD: "On hold", RESOLVED: "Resolved",
              CANCELLED: "Cancelled"}
    TONES = {OPEN: "red", IN_PROGRESS: "cyan", ON_HOLD: "amber", RESOLVED: "green", CANCELLED: "gray"}


class TicketCategory:
    LABELS = {
        "plumbing": "Plumbing",
        "electrical": "Electrical",
        "hvac": "Heating / AC",
        "appliance": "Appliance",
        "furniture": "Furniture & fixtures",
        "electronics": "TV / Wi-Fi / Phone",
        "locks": "Doors & locks",
        "pest": "Pest control",
        "structural": "Walls / floors / windows",
        "exterior": "Exterior & grounds",
        "other": "Other",
    }


class IdType:
    LABELS = {
        "drivers_license": "Driver's license",
        "passport": "Passport",
        "state_id": "State / national ID",
        "military_id": "Military ID",
        "other": "Other",
    }


def label(mapping: dict, value, default: str = "") -> str:
    return mapping.get(value, default or (str(value).replace("_", " ").title() if value else ""))
