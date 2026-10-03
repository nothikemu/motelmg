import sqlite3
from datetime import date

import pytest

from motelmg.core.dates import add_months, month_bounds, parse_time
from motelmg.core.errors import ConflictError, DatabaseError, ValidationError
from motelmg.core.money import CurrencyFormat, parse_amount, parse_percent, percent_of
from motelmg.core import validation as v
from motelmg.data.database import Database
from motelmg.data.migrations import LATEST_VERSION, migrate
from motelmg.services.context import AppContext
from tests.conftest import ADMIN, book, make_context, new_guest


@pytest.mark.parametrize("text,cents", [("12", 1200), ("12.5", 1250), ("$1,234.56", 123456), (" 0.01 ", 1),
                                        ("10.005", 1001), (7, 700)])
def test_parse_amount(text, cents):
    assert parse_amount(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "-5", "1e400", "NaN", True])
def test_parse_amount_rejects(text):
    with pytest.raises(ValidationError):
        parse_amount(text)


def test_currency_formatting():
    usd = CurrencyFormat()
    assert usd.format(123456) == "$1,234.56"
    assert usd.format(-500) == "-$5.00"
    eur = CurrencyFormat("EUR", "€", 2, True, ".", ",")
    assert eur.format(123456) == "1.234,56 €"
    jpy = CurrencyFormat("JPY", "¥", 0)
    assert jpy.format(150050) == "¥1,501"
    assert usd.plain(-1999) == "-19.99"


def test_percentages():
    assert parse_percent("8.25%") == 825
    assert percent_of(10_000, 825) == 825
    assert percent_of(-1999, 1000) == -200
    with pytest.raises(ValidationError):
        parse_percent("150")


def test_dates_and_validation():
    assert month_bounds(2024, 2) == (date(2024, 2, 1), date(2024, 2, 29))
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert parse_time("3:30 PM").hour == 15
    assert v.email("John@Example.COM") == "john@example.com"
    with pytest.raises(ValidationError):
        v.email("not-an-email")
    with pytest.raises(ValidationError):
        v.phone("12")
    assert v.phone("+1 (555) 123-4567") == "+1 (555) 123-4567"


def test_migrations_are_idempotent_and_versioned(tmp_path):
    db = Database(tmp_path / "x.db")
    assert migrate(db) == LATEST_VERSION
    assert migrate(db) == LATEST_VERSION
    assert db.scalar("SELECT COUNT(*) FROM roles") == 5
    assert db.scalar("PRAGMA foreign_keys") == 1
    db.execute(f"PRAGMA user_version = {LATEST_VERSION + 1}")
    with pytest.raises(DatabaseError, match="newer version"):
        migrate(db)


def test_nested_transactions_roll_back_cleanly(tmp_path):
    db = Database(tmp_path / "t.db")
    migrate(db)
    with db.transaction():
        db.execute("INSERT INTO counters(name, value) VALUES ('a', 1)")
        with pytest.raises(RuntimeError):
            with db.transaction():
                db.execute("INSERT INTO counters(name, value) VALUES ('b', 1)")
                raise RuntimeError("boom")
    assert db.scalar("SELECT COUNT(*) FROM counters WHERE name IN ('a', 'b')") == 1
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute("INSERT INTO counters(name, value) VALUES ('c', 1)")
            raise RuntimeError("boom")
    assert db.scalar("SELECT COUNT(*) FROM counters WHERE name = 'c'") == 0


def test_constraints_translate_to_friendly_errors(ctx):
    with pytest.raises(ValidationError, match="already exists"):
        ctx.rooms.save_room(None, {"number": "101", "room_type_id": ctx.rooms.list_types()[0].id})
    with pytest.raises(ValidationError, match="already exists"):
        ctx.db.insert("rooms", {"number": "101", "room_type_id": 1, "created_at": "x", "updated_at": "x"})
    with pytest.raises(ValidationError):
        ctx.db.execute("UPDATE rooms SET hk_status = 'sparkly'")
    new_guest(ctx, "Same", "Doc", id_number="ZZ1")
    with pytest.raises(ValidationError, match="ID document"):
        new_guest(ctx, "Other", "Person", id_number="ZZ1")


def test_data_persists_across_restarts(db_path):
    ctx = make_context(db_path)
    guest_id = new_guest(ctx, "Persist", "Ent")
    res_id = book(ctx, guest_id)
    ctx.close()
    again = AppContext(db_path)
    assert again.settings.setup_complete
    assert again.auth.login(ADMIN["username"], ADMIN["password"]).username == "admin"
    assert again.guests.get(guest_id).full_name == "Persist Ent"
    assert again.reservations.get(res_id).confirmation_no == "R10001"
    again.close()


def test_raw_sqlite_cannot_create_inconsistent_folio(ctx):
    res_id = book(ctx, new_guest(ctx))
    with pytest.raises(sqlite3.IntegrityError):
        ctx.db.conn.execute("INSERT INTO charges(reservation_id, kind, description, service_date, quantity, "
                            "unit_amount, amount, posted_at) VALUES (?, 'extra', 'x', '2026-01-01', 2, 5, 11, 'x')",
                            (res_id,))
    with pytest.raises(sqlite3.IntegrityError):
        ctx.db.conn.execute("INSERT INTO payments(reservation_id, kind, method_id, amount, receipt_no, created_at) "
                            "VALUES (?, 'payment', 1, -5, 'r', 'x')", (res_id,))
    with pytest.raises(ConflictError):
        ctx.db.execute("DELETE FROM guests")
