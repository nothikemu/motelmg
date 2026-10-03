import csv
from datetime import date, datetime, timedelta

import pytest

from motelmg.core.errors import ConflictError, ValidationError
from motelmg.reporting.documents import report_html
from motelmg.reporting.export import report_to_csv
from motelmg.services.context import AppContext
from motelmg.services.setup import DEFAULT_ROOM_TYPES, DEFAULT_ROOMS, SetupService
from tests.conftest import ADMIN, book, cash, new_guest


@pytest.fixture
def demo_ctx(tmp_path):
    ctx = AppContext(tmp_path / "demo.db")
    SetupService(ctx).complete({"admin": ADMIN, "property": {"property.name": "Demo Inn"}, "currency": "USD",
                                "tax_rate": "9", "nightly_tax": "1.5", "room_types": DEFAULT_ROOM_TYPES,
                                "rooms": DEFAULT_ROOMS, "demo": True})
    yield ctx
    ctx.close()


def test_demo_data_is_internally_consistent(demo_ctx):
    ctx = demo_ctx
    db = ctx.db
    assert db.scalar("SELECT COUNT(*) FROM reservations") > 100
    # no overlapping active bookings per room
    overlaps = db.scalar(
        "SELECT COUNT(*) FROM reservations a JOIN reservations b ON a.room_id = b.room_id AND a.id < b.id "
        "WHERE a.status IN ('confirmed','checked_in') AND b.status IN ('confirmed','checked_in') "
        "AND a.check_in_date < b.check_out_date AND a.check_out_date > b.check_in_date")
    assert overlaps == 0
    # every checked-out stay has an invoice, one room charge per night
    assert db.scalar("SELECT COUNT(*) FROM reservations r WHERE status = 'checked_out' AND NOT EXISTS "
                     "(SELECT 1 FROM invoices i WHERE i.reservation_id = r.id)") == 0
    bad_nights = db.scalar(
        "SELECT COUNT(*) FROM reservations r WHERE r.status IN ('checked_in','checked_out') AND "
        "(SELECT COUNT(*) FROM charges c WHERE c.reservation_id = r.id AND c.kind = 'room' AND c.is_void = 0) "
        "<> CAST(julianday(r.check_out_date) - julianday(r.check_in_date) AS INTEGER)")
    assert bad_nights == 0
    # at most one in-house reservation per room; occupied rooms are not out of service
    assert db.scalar("SELECT COUNT(*) FROM reservations r JOIN rooms m ON m.id = r.room_id "
                     "WHERE r.status = 'checked_in' AND m.service_status <> 'in_service'") == 0
    assert db.integrity_check() == "ok"
    assert ctx.session.username == "admin"


def test_every_report_runs_and_exports(demo_ctx, tmp_path):
    ctx = demo_ctx
    today = ctx.clock.today()
    start = today - timedelta(days=30)
    for report in ctx.reports.available():
        params = {"range": {"start": start, "end": today}, "year": {"year": today.year}, "none": {}}[report.params]
        result = ctx.reports.run(report.key, **params)
        assert result.title and result.columns
        out = tmp_path / f"{report.key}.csv"
        report_to_csv(result, out, ctx.settings.currency())
        with out.open(encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == [c.title or c.key for c in result.columns]
        assert "<table" in report_html(ctx, result, lambda v, k: str(v))
    revenue = ctx.reports.run("daily_revenue", start=start, end=today)
    assert revenue.totals["total"] > 0
    occupancy = ctx.reports.run("occupancy", start=start, end=today)
    assert 0 < occupancy.totals["occupancy"] <= 100
    outstanding = ctx.reports.run("outstanding")
    assert outstanding.totals["balance"] == sum(r["total"] - r["paid"] for r in ctx.billing.outstanding())


def test_dashboard_alerts_and_search(demo_ctx):
    ctx = demo_ctx
    data = ctx.dashboard.data()
    assert data.total_rooms == len(DEFAULT_ROOMS)
    assert data.occupied + data.available + data.vacant_dirty + data.out_of_order + \
        data.state_counts.get("reserved", 0) == data.total_rooms
    alerts = ctx.alerts.current()
    assert alerts
    ctx.alerts.dismiss(alerts[0].key)
    assert alerts[0].key not in {a.key for a in ctx.alerts.current()}
    ctx.alerts.restore_dismissed()
    assert alerts[0].key in {a.key for a in ctx.alerts.current()}
    guest = ctx.guests.search("")[0]
    hits = ctx.search.search(guest.last_name)
    assert any(h.kind == "guest" and h.id == guest.id for h in hits)
    res = ctx.repo_res.search(limit=1)[0]
    assert any(h.kind == "reservation" for h in ctx.search.search(res.confirmation_no))
    assert any(h.kind == "room" for h in ctx.search.search("10"))


def test_backup_and_restore_roundtrip(ctx, tmp_path):
    ctx.settings.update({"backup.directory": str(tmp_path / "backups")})
    guest_id = new_guest(ctx, "Before", "Backup")
    path = ctx.backups.backup_now()
    assert path.exists() and ctx.backups.list()[0].path == path
    details = ctx.backups.inspect(path)
    assert details.guests == 1 and details.property_name == "Test Motel"
    new_guest(ctx, "After", "Backup")
    assert len(ctx.guests.search("")) == 2
    safety = ctx.backups.restore(path)
    assert safety.exists()
    assert ctx.session is None  # everyone must sign in again
    ctx.auth.login("admin", "Admin1234")
    names = [g.full_name for g in ctx.guests.search("")]
    assert names == ["Before Backup"] and ctx.guests.get(guest_id)
    assert ctx.audit.search(action_prefix="backup.restore")


def test_restore_rejects_invalid_files(ctx, tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a database at all" * 100)
    with pytest.raises(ValidationError):
        ctx.backups.inspect(junk)
    with pytest.raises(ValidationError):
        ctx.backups.restore(tmp_path / "missing.db")


def test_automatic_backup_schedule(ctx, tmp_path):
    ctx.settings.update({"backup.directory": str(tmp_path / "auto"), "backup.frequency": "daily"})
    assert ctx.backups.is_due()
    assert ctx.backups.auto_backup_if_due() is not None
    assert not ctx.backups.is_due()
    ctx.clock.advance(days=1, minutes=1)
    assert ctx.backups.is_due()
    ctx.settings.update({"backup.frequency": "on_exit"})
    assert not ctx.backups.is_due() and ctx.backups.backup_on_exit() is not None


def test_setup_validation(tmp_path):
    ctx = AppContext(tmp_path / "fresh.db")
    setup = SetupService(ctx)
    assert setup.needed()
    with pytest.raises(ValidationError) as exc:
        setup.validate_admin({"full_name": "", "username": "a", "password": "abc", "confirm": "xyz"})
    assert {"full_name", "username", "password", "confirm"} <= set(exc.value.field_errors)
    with pytest.raises(ValidationError):
        setup.complete({"admin": ADMIN, "property": {"property.name": "X"}, "room_types": [], "rooms": []})
    assert not ctx.auth.has_users()  # nothing half-created
    setup.complete({"admin": ADMIN, "property": {"property.name": "X"}, "room_types": DEFAULT_ROOM_TYPES,
                    "rooms": DEFAULT_ROOMS})
    assert not setup.needed()
    with pytest.raises(ConflictError):
        setup.complete({"admin": ADMIN, "property": {"property.name": "X"}, "room_types": DEFAULT_ROOM_TYPES,
                        "rooms": DEFAULT_ROOMS})
    ctx.close()


def test_guest_crud_duplicates_and_history(ctx):
    data = {"first_name": "maria", "last_name": "garcia", "email": "maria@example.com", "phone": "(555) 222-3333"}
    gid = ctx.guests.create(data)
    assert ctx.guests.get(gid).full_name == "Maria Garcia"
    dupes = ctx.guests.find_duplicates({"first_name": "M", "last_name": "G", "phone": "555.222.3333"})
    assert [g.id for g in dupes] == [gid]
    with pytest.raises(ValidationError) as exc:
        ctx.guests.create({"first_name": "", "last_name": "X", "email": "bad", "date_of_birth": "2099-01-01"})
    assert {"first_name", "email", "date_of_birth"} <= set(exc.value.field_errors)
    with pytest.raises(ValidationError, match="why"):
        ctx.guests.update(gid, {**data, "is_banned": True})
    ctx.guests.update(gid, {**data, "is_vip": True, "preferences": "Feather-free pillows"})
    assert ctx.guests.get(gid).is_vip
    res_id = book(ctx, gid)
    with pytest.raises(ConflictError, match="cannot be deleted"):
        ctx.guests.delete(gid)
    ctx.clock.set(datetime(2026, 3, 10, 15))
    ctx.reservations.check_in(res_id, allow_dirty=True) if ctx.guests.get(gid).id_number else None
    assert [r.id for r in ctx.guests.history(gid)] == [res_id]
    note = ctx.notes.add("Allergic to cats", important=True, guest_id=gid)
    assert ctx.notes.important_for_guest(gid)[0].body == "Allergic to cats"
    ctx.notes.delete(note)
    other = ctx.guests.create({"first_name": "Temp", "last_name": "Person"})
    ctx.guests.delete(other)
    assert cash(ctx) and date.today()
