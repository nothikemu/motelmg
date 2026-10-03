"""Domain models (plain dataclasses) shared by the service and UI layers."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, TypeVar

from motelmg.core.dates import parse_date, parse_datetime

T = TypeVar("T")


def from_row(cls: type[T], row: Any) -> T:
    """Build a dataclass from a ``sqlite3.Row`` ignoring unknown columns and
    converting ``*_date`` / timestamp columns to ``date``/``datetime``."""
    keys = row.keys()
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):  # type: ignore[arg-type]
        if f.name not in keys:
            continue
        value = row[f.name]
        ftype = str(f.type)
        if value is not None and isinstance(value, str):
            if ftype.startswith("date") and not ftype.startswith("datetime"):
                value = parse_date(value)
            elif ftype.startswith("datetime"):
                value = parse_datetime(value)
        if ftype.startswith("bool") and value is not None:
            value = bool(value)
        kwargs[f.name] = value
    return cls(**kwargs)  # type: ignore[call-arg]


@dataclass
class Role:
    id: int
    name: str
    description: str = ""
    is_system: bool = False
    permissions: frozenset[str] = frozenset()
    user_count: int = 0


@dataclass
class User:
    id: int
    username: str
    full_name: str
    role_id: int
    email: str = ""
    phone: str = ""
    is_active: bool = True
    must_change_password: bool = False
    failed_attempts: int = 0
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    role_name: str = ""


@dataclass
class RoomType:
    id: int
    code: str
    name: str
    base_rate: int
    description: str = ""
    beds: str = ""
    max_occupancy: int = 2
    is_active: bool = True
    sort_order: int = 0
    room_count: int = 0


@dataclass
class Room:
    id: int
    number: str
    room_type_id: int
    floor: str = ""
    beds: str = ""
    max_occupancy: int | None = None
    rate: int | None = None
    description: str = ""
    features: str = ""
    hk_status: str = "clean"
    service_status: str = "in_service"
    service_reason: str = ""
    service_until: date | None = None
    is_active: bool = True
    sort_order: int = 0
    # joined
    type_name: str = ""
    type_code: str = ""
    type_beds: str = ""
    type_max_occupancy: int = 2
    type_rate: int = 0

    @property
    def effective_rate(self) -> int:
        return self.rate if self.rate is not None else self.type_rate

    @property
    def effective_beds(self) -> str:
        return self.beds or self.type_beds

    @property
    def capacity(self) -> int:
        return self.max_occupancy or self.type_max_occupancy

    @property
    def is_sellable_now(self) -> bool:
        return self.is_active and self.service_status == "in_service"


@dataclass
class Guest:
    id: int
    first_name: str
    last_name: str
    email: str = ""
    phone: str = ""
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    company: str = ""
    id_type: str = ""
    id_number: str = ""
    id_expiry: date | None = None
    date_of_birth: date | None = None
    vehicle_plate: str = ""
    preferences: str = ""
    is_vip: bool = False
    is_banned: bool = False
    banned_reason: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # aggregates
    stays: int = 0
    nights: int = 0
    total_spent: int = 0
    last_stay: date | None = None
    in_house: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_name(self) -> str:
        return f"{self.last_name}, {self.first_name}"

    @property
    def address_text(self) -> str:
        parts = [self.address_line1, self.address_line2,
                 " ".join(p for p in (self.city + ("," if self.city and self.state else ""),
                                      self.state, self.postal_code) if p).strip(),
                 self.country]
        return "\n".join(p for p in parts if p)


@dataclass
class Reservation:
    id: int
    confirmation_no: str
    guest_id: int
    room_id: int
    room_type_id: int
    check_in_date: date
    check_out_date: date
    status: str
    nightly_rate: int
    adults: int = 1
    children: int = 0
    source: str = "phone"
    is_walk_in: bool = False
    rate_overridden: bool = False
    discount_name: str = ""
    discount_bp: int = 0
    expected_arrival: str = ""
    late_checkout_until: str = ""
    special_requests: str = ""
    actual_check_in: datetime | None = None
    actual_check_out: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: int | None = None
    # joined
    guest_name: str = ""
    guest_phone: str = ""
    guest_email: str = ""
    guest_is_vip: bool = False
    room_number: str = ""
    room_type_name: str = ""
    created_by_name: str = ""
    total: int = 0
    paid: int = 0
    balance: int = 0

    @property
    def nights(self) -> int:
        return (self.check_out_date - self.check_in_date).days

    @property
    def guests_count(self) -> int:
        return self.adults + self.children

    @property
    def is_active(self) -> bool:
        return self.status in ("confirmed", "checked_in")


@dataclass
class Charge:
    id: int
    reservation_id: int
    kind: str
    description: str
    service_date: date
    quantity: int
    unit_amount: int
    amount: int
    taxable: bool = False
    parent_id: int | None = None
    tax_id: int | None = None
    room_id: int | None = None
    charge_item_id: int | None = None
    is_void: bool = False
    void_reason: str = ""
    posted_at: datetime | None = None
    posted_by_name: str = ""


@dataclass
class Payment:
    id: int
    reservation_id: int
    kind: str
    method_id: int
    amount: int
    receipt_no: str
    reference: str = ""
    notes: str = ""
    is_void: bool = False
    void_reason: str = ""
    created_at: datetime | None = None
    method_name: str = ""
    created_by_name: str = ""
    confirmation_no: str = ""
    guest_name: str = ""
    room_number: str = ""

    @property
    def signed_amount(self) -> int:
        return -self.amount if self.kind == "refund" else self.amount


@dataclass
class TaxSummary:
    name: str
    amount: int


@dataclass
class Folio:
    reservation: Reservation
    charges: list[Charge] = field(default_factory=list)  # non-tax lines (incl. void)
    tax_lines: list[Charge] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    taxes: list[TaxSummary] = field(default_factory=list)
    subtotal: int = 0
    tax_total: int = 0
    total: int = 0
    paid: int = 0
    balance: int = 0
    invoice_no: str = ""
    invoice_issued_at: datetime | None = None


@dataclass
class QuoteLine:
    description: str
    amount: int
    kind: str = "room"


@dataclass
class Quote:
    nights: int
    nightly_rate: int
    room_total: int
    discount_total: int
    fees_total: int
    subtotal: int
    taxes: list[TaxSummary]
    tax_total: int
    total: int
    lines: list[QuoteLine] = field(default_factory=list)
    deposit_suggested: int = 0


@dataclass
class PaymentMethod:
    id: int
    name: str
    requires_reference: bool = False
    is_cash: bool = False
    is_active: bool = True
    sort_order: int = 0


@dataclass
class Tax:
    id: int
    name: str
    kind: str
    value: int
    applies_to: str = "all"
    is_active: bool = True
    sort_order: int = 0


@dataclass
class ChargeItem:
    id: int
    name: str
    category: str
    default_amount: int
    taxable: bool = True
    auto_apply: str = "none"
    system_code: str | None = None
    is_active: bool = True
    sort_order: int = 0


@dataclass
class DiscountType:
    id: int
    name: str
    percent_bp: int
    is_active: bool = True
    sort_order: int = 0


@dataclass
class HKTask:
    id: int
    room_id: int
    task_type: str
    priority: int
    status: str
    due_date: date
    assigned_to: int | None = None
    notes: str = ""
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    inspected_at: datetime | None = None
    inspection_notes: str = ""
    room_number: str = ""
    room_type_name: str = ""
    floor: str = ""
    hk_status: str = ""
    assigned_name: str = ""
    completed_by_name: str = ""
    inspected_by_name: str = ""
    arrival_today: bool = False
    occupied: bool = False


@dataclass
class MaintenanceTicket:
    id: int
    title: str
    category: str
    priority: int
    status: str
    room_id: int | None = None
    location: str = ""
    description: str = ""
    blocks_room: bool = False
    assigned_to: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: str = ""
    cost: int = 0
    room_number: str = ""
    reported_by_name: str = ""
    resolved_by_name: str = ""

    @property
    def where(self) -> str:
        return f"Room {self.room_number}" if self.room_id else self.location


@dataclass
class Note:
    id: int
    body: str
    is_important: bool = False
    created_at: datetime | None = None
    author: str = ""
    guest_id: int | None = None
    reservation_id: int | None = None
    room_id: int | None = None


@dataclass
class AuditEntry:
    id: int
    ts: datetime
    username: str
    action: str
    entity_type: str
    entity_id: int | None
    summary: str
    details: str = ""


@dataclass
class RoomMove:
    id: int
    reservation_id: int
    from_room: str
    to_room: str
    moved_at: datetime
    reason: str = ""
    moved_by_name: str = ""
