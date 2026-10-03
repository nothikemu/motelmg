"""Configuration keys and their default values.

Every configurable value lives in the ``settings`` table of the database so it
is backed up together with the data. This module is the single source of
truth for the available keys and defaults.
"""

from __future__ import annotations

DEFAULT_SETTINGS: dict[str, object] = {
    # Property
    "property.name": "My Motel",
    "property.address1": "",
    "property.address2": "",
    "property.city": "",
    "property.state": "",
    "property.postal_code": "",
    "property.country": "",
    "property.phone": "",
    "property.email": "",
    "property.website": "",
    "property.tax_id": "",
    # Currency
    "currency.code": "USD",
    "currency.symbol": "$",
    "currency.decimals": 2,
    "currency.symbol_after": False,
    "currency.thousands_sep": ",",
    "currency.decimal_sep": ".",
    # Front desk policies
    "policy.check_in_time": "15:00",
    "policy.check_out_time": "11:00",
    "policy.late_checkout_grace_minutes": 30,
    "policy.early_checkin_grace_minutes": 60,
    "policy.require_inspection": False,
    "policy.require_guest_id": True,
    "policy.max_nights": 60,
    "policy.booking_horizon_days": 730,
    "policy.deposit_percent": 0,
    # Numbering
    "numbering.reservation_prefix": "R",
    "numbering.invoice_prefix": "INV-",
    "numbering.receipt_prefix": "RC-",
    # Invoices & receipts
    "invoice.header_text": "",
    "invoice.footer_text": "Thank you for staying with us! We hope to see you again soon.",
    "invoice.show_tax_breakdown": True,
    "invoice.show_tax_lines": False,
    "invoice.paper_size": "Letter",
    "invoice.print_registration_card": False,
    # Notifications
    "notify.arrivals": True,
    "notify.departures": True,
    "notify.overdue": True,
    "notify.no_shows": True,
    "notify.balances": True,
    "notify.housekeeping": True,
    "notify.maintenance": True,
    "notify.conflicts": True,
    "notify.system": True,
    "notify.toasts": True,
    "notify.arrival_window_hours": 2,
    "notify.balance_threshold": 0,
    # Backups
    "backup.auto_enabled": True,
    "backup.frequency": "daily",  # daily | weekly | on_exit
    "backup.directory": "",  # empty = default folder inside the data directory
    "backup.keep": 14,
    "backup.last_at": "",
    # Application
    "app.setup_complete": False,
    "app.theme": "light",  # light | dark | system
    "app.date_format": "MMM d, yyyy",
    "app.time_format": "h:mm AP",
    "app.auto_lock_minutes": 0,
    "app.week_starts_monday": False,
}

DATE_FORMAT_CHOICES = [
    ("MMM d, yyyy", "Oct 3, 2026"),
    ("MM/dd/yyyy", "10/03/2026"),
    ("dd/MM/yyyy", "03/10/2026"),
    ("yyyy-MM-dd", "2026-10-03"),
    ("d MMM yyyy", "3 Oct 2026"),
]

TIME_FORMAT_CHOICES = [
    ("h:mm AP", "3:30 PM"),
    ("HH:mm", "15:30"),
]
