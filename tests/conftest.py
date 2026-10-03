from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from motelmg.core.dates import Clock  # noqa: E402
from motelmg.services.context import AppContext  # noqa: E402
from motelmg.services.setup import SetupService  # noqa: E402

START = datetime(2026, 3, 10, 9, 0, 0)  # a Tuesday morning

ROOM_TYPES = [
    {"code": "SQ", "name": "Standard Queen", "beds": "1 Queen", "max_occupancy": 2, "base_rate": "100.00"},
    {"code": "DQ", "name": "Double Queen", "beds": "2 Queens", "max_occupancy": 4, "base_rate": "150.00"},
]
ROOMS = [
    {"number": "101", "type_code": "SQ", "floor": "1"},
    {"number": "102", "type_code": "SQ", "floor": "1"},
    {"number": "201", "type_code": "DQ", "floor": "2"},
]
ADMIN = {"full_name": "Alex Admin", "username": "admin", "password": "Admin1234", "confirm": "Admin1234"}


def make_context(path, *, tax_rate="10", nightly_tax="2", clock=None) -> AppContext:
    ctx = AppContext(path, clock=clock or Clock(START))
    SetupService(ctx).complete({
        "admin": ADMIN, "property": {"property.name": "Test Motel", "property.city": "Springfield"},
        "currency": "USD", "tax_rate": tax_rate, "nightly_tax": nightly_tax,
        "room_types": ROOM_TYPES, "rooms": ROOMS,
    })
    return ctx


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "motelmg.db"


@pytest.fixture
def ctx(db_path):
    context = make_context(db_path)
    yield context
    context.close()


@pytest.fixture
def notax_ctx(tmp_path):
    context = make_context(tmp_path / "notax.db", tax_rate="0", nightly_tax="0")
    yield context
    context.close()


def room(ctx, number: str):
    return ctx.repo_rooms.get_by_number(number)


def new_guest(ctx, first="Jane", last="Doe", **extra) -> int:
    data = {"first_name": first, "last_name": last, "phone": "555-123-4567", "email": f"{first.lower()}@example.com",
            "id_type": "drivers_license", "id_number": f"D{abs(hash((first, last))) % 10**7}"}
    data.update(extra)
    return ctx.guests.create(data)


def book(ctx, guest_id, room_number="101", arrive=None, nights=2, **extra) -> int:
    from datetime import timedelta
    arrive = arrive or ctx.clock.today()
    data = {"guest_id": guest_id, "room_id": room(ctx, room_number).id, "check_in_date": arrive,
            "check_out_date": arrive + timedelta(days=nights), "adults": 1}
    data.update(extra)
    return ctx.reservations.create(data)


def cash(ctx) -> int:
    return next(m.id for m in ctx.catalog.payment_methods() if m.is_cash)


def card(ctx) -> int:
    return next(m.id for m in ctx.catalog.payment_methods() if m.name == "Credit card")


def login_as(ctx, role_name: str, username: str | None = None):
    """Create (if needed) and sign in a user with the given role."""
    username = username or role_name.lower().replace(" ", "")
    if not ctx.repo_staff.get_user_row(username):
        ctx.auth.login(ADMIN["username"], ADMIN["password"])
        role_id = next(r.id for r in ctx.users.list_roles() if r.name == role_name)
        ctx.users.create_user({"full_name": f"{role_name} User", "username": username, "role_id": role_id},
                              "Password123", must_change=False)
    return ctx.auth.login(username, "Password123")
