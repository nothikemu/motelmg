"""Reference data inserted when a database is first created."""

from __future__ import annotations

import json
from datetime import datetime

from motelmg.core.config import DEFAULT_SETTINGS
from motelmg.core.permissions import ADMIN_ROLE, DEFAULT_ROLES
from motelmg.data.database import Database

DEFAULT_PAYMENT_METHODS = [
    # name, requires_reference, is_cash
    ("Cash", 0, 1),
    ("Credit card", 1, 0),
    ("Debit card", 1, 0),
    ("Check", 1, 0),
    ("Bank transfer", 1, 0),
    ("Gift certificate", 1, 0),
]

DEFAULT_CHARGE_ITEMS = [
    # name, category, amount(cents), taxable, auto_apply, system_code
    ("Early check-in", "fee", 2000, 1, "none", "EARLY_CHECKIN"),
    ("Late check-out", "fee", 2000, 1, "none", "LATE_CHECKOUT"),
    ("Cancellation fee", "fee", 0, 0, "none", "CANCELLATION"),
    ("No-show fee", "fee", 0, 0, "none", "NO_SHOW"),
    ("Early departure fee", "fee", 0, 1, "none", "EARLY_DEPARTURE"),
    ("Pet fee", "fee", 1500, 1, "none", None),
    ("Extra person", "fee", 1000, 1, "none", None),
    ("Rollaway bed", "extra", 1500, 1, "none", None),
    ("Smoking / cleaning fee", "fee", 15000, 0, "none", None),
    ("Damage", "fee", 0, 0, "none", None),
    ("Laundry", "extra", 800, 1, "none", None),
    ("Vending / snacks", "extra", 300, 1, "none", None),
    ("Parking", "extra", 0, 1, "none", None),
    ("Lost key card", "fee", 500, 0, "none", None),
]

DEFAULT_DISCOUNTS = [
    ("AAA / CAA", 1000),
    ("Senior", 1000),
    ("Military", 1500),
    ("Weekly stay", 1500),
    ("Corporate", 1000),
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def seed_reference_data(db: Database) -> None:
    now = _now()
    for key, value in DEFAULT_SETTINGS.items():
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, json.dumps(value)))

    for name, (description, perms) in DEFAULT_ROLES.items():
        existing = db.one("SELECT id FROM roles WHERE name = ?", (name,))
        if existing:
            continue
        role_id = db.insert("roles", {
            "name": name, "description": description,
            "is_system": 1 if name == ADMIN_ROLE else 0, "created_at": now,
        })
        db.executemany("INSERT INTO role_permissions(role_id, permission) VALUES (?, ?)",
                       [(role_id, p) for p in sorted(perms)])

    if not db.scalar("SELECT COUNT(*) FROM payment_methods"):
        for order, (name, ref, cash) in enumerate(DEFAULT_PAYMENT_METHODS):
            db.insert("payment_methods", {"name": name, "requires_reference": ref, "is_cash": cash,
                                          "sort_order": order})
    if not db.scalar("SELECT COUNT(*) FROM charge_items"):
        for order, (name, cat, amount, taxable, auto, code) in enumerate(DEFAULT_CHARGE_ITEMS):
            db.insert("charge_items", {"name": name, "category": cat, "default_amount": amount,
                                       "taxable": taxable, "auto_apply": auto, "system_code": code,
                                       "sort_order": order})
    if not db.scalar("SELECT COUNT(*) FROM discount_types"):
        for order, (name, bp) in enumerate(DEFAULT_DISCOUNTS):
            db.insert("discount_types", {"name": name, "percent_bp": bp, "sort_order": order})

    for counter, start in (("reservation", 10000), ("invoice", 0), ("receipt", 0)):
        db.execute("INSERT OR IGNORE INTO counters(name, value) VALUES (?, ?)", (counter, start))
