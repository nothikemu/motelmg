from datetime import datetime, timedelta

import pytest

from motelmg.core.enums import HKStatus, RoomState, ServiceStatus, TaskStatus, TicketStatus
from motelmg.core.errors import ConflictError, PermissionDenied, ValidationError
from tests.conftest import book, login_as, new_guest, room


def state(ctx, number):
    return next(i for i in ctx.rooms.board() if i.room.number == number).state


def test_room_and_type_management(ctx):
    type_id = ctx.rooms.save_type(None, {"code": "acc", "name": "Accessible King", "base_rate": "110",
                                         "max_occupancy": 2, "beds": "1 King"})
    assert ctx.rooms.get_type(type_id).code == "ACC"
    with pytest.raises(ValidationError) as exc:
        ctx.rooms.save_type(None, {"code": "", "name": "", "base_rate": "-1"})
    assert {"code", "name", "base_rate"} <= set(exc.value.field_errors)
    room_id = ctx.rooms.save_room(None, {"number": "103a", "room_type_id": type_id, "floor": "1", "rate": "115"})
    r = ctx.rooms.get(room_id)
    assert r.number == "103A" and r.effective_rate == 115_00 and r.capacity == 2
    with pytest.raises(ValidationError):
        ctx.rooms.save_room(None, {"number": "bad room!", "room_type_id": type_id})
    with pytest.raises(ConflictError):
        ctx.rooms.delete_type(type_id)
    assert ctx.rooms.delete_room(room_id) == "deleted"
    ctx.rooms.delete_type(type_id)


def test_room_with_history_is_archived_not_deleted(ctx):
    res_id = book(ctx, new_guest(ctx), "102", nights=1)
    with pytest.raises(ConflictError, match="upcoming"):
        ctx.rooms.delete_room(room(ctx, "102").id)
    ctx.reservations.cancel(res_id, "x")
    assert ctx.rooms.delete_room(room(ctx, "102").id) == "deactivated"
    assert "102" not in [r.number for r in ctx.rooms.list_rooms()]


def test_out_of_service_flow_with_conflict_warning(ctx):
    upcoming = book(ctx, new_guest(ctx), "101", arrive=ctx.clock.today() + timedelta(days=2))
    conflicts = ctx.rooms.set_service_status(room(ctx, "101").id, ServiceStatus.OUT_OF_SERVICE, "Carpet replacement")
    assert [c["id"] for c in conflicts] == [upcoming]
    assert state(ctx, "101") == RoomState.OUT_OF_SERVICE
    assert any(a.key == f"conflict:{upcoming}" for a in ctx.alerts.current())
    ctx.reservations.transfer(upcoming, room(ctx, "102").id, "Room 101 out of service")
    assert not any(a.key.startswith("conflict:") for a in ctx.alerts.current())
    ctx.rooms.set_service_status(room(ctx, "101").id, ServiceStatus.IN_SERVICE, "")
    assert room(ctx, "101").hk_status == HKStatus.DIRTY  # must be cleaned before selling


def test_cannot_take_occupied_room_out_of_service(ctx):
    res_id = book(ctx, new_guest(ctx), "101")
    ctx.clock.set(datetime(2026, 3, 10, 15))
    ctx.reservations.check_in(res_id)
    with pytest.raises(ConflictError, match="occupied"):
        ctx.rooms.set_service_status(room(ctx, "101").id, ServiceStatus.MAINTENANCE, "Leak")
    with pytest.raises(ConflictError, match="occupied"):
        ctx.maintenance.create({"room_id": room(ctx, "101").id, "title": "Leak", "blocks_room": True})
    ticket_id, _ = ctx.maintenance.create({"room_id": room(ctx, "101").id, "title": "Leak"})
    assert ctx.maintenance.get(ticket_id).status == TicketStatus.OPEN


def test_maintenance_ticket_blocks_and_releases_room(ctx):
    r = room(ctx, "102")
    with pytest.raises(ValidationError):
        ctx.maintenance.create({"title": "", "room_id": None})
    t1, _ = ctx.maintenance.create({"room_id": r.id, "title": "AC broken", "category": "hvac", "priority": 1,
                                    "blocks_room": True})
    t2, _ = ctx.maintenance.create({"room_id": r.id, "title": "Lamp", "blocks_room": True})
    assert room(ctx, "102").service_status == ServiceStatus.MAINTENANCE
    assert any(a.key == f"ticket:{t1}" for a in ctx.alerts.current())
    with pytest.raises(ConflictError):
        book(ctx, new_guest(ctx), "102")
    ctx.maintenance.set_status(t1, TicketStatus.IN_PROGRESS, "Technician on site")
    ctx.maintenance.resolve(t1, "Replaced compressor", "250")
    assert room(ctx, "102").service_status == ServiceStatus.MAINTENANCE  # t2 still blocks
    ctx.maintenance.resolve(t2, "Duplicate", cancelled=True)
    r = room(ctx, "102")
    assert r.service_status == ServiceStatus.IN_SERVICE and r.hk_status == HKStatus.DIRTY
    assert ctx.housekeeping.tasks(statuses=["pending"], room_id=r.id)[0].task_type == "touch_up"
    assert ctx.maintenance.get(t1).cost == 250_00
    with pytest.raises(ConflictError):
        ctx.maintenance.resolve(t1, "again")
    general, _ = ctx.maintenance.create({"location": "Parking lot", "title": "Light out", "category": "exterior"})
    assert ctx.maintenance.get(general).where == "Parking lot"


def test_housekeeping_permissions_and_inspection_failure(ctx):
    r = room(ctx, "101")
    ctx.housekeeping.set_room_status(r.id, HKStatus.DIRTY, "Guest spill")
    task = ctx.housekeeping.tasks(statuses=["pending"], room_id=r.id)[0]
    maria = login_as(ctx, "Housekeeping", "maria")
    other = login_as(ctx, "Housekeeping", "ana")
    ctx.auth.login("admin", "Admin1234")
    ctx.housekeeping.assign([task.id], maria.user_id)
    ctx.auth.login("ana", "Password123")
    with pytest.raises(PermissionDenied, match="assigned to"):
        ctx.housekeeping.start(task.id)
    with pytest.raises(PermissionDenied):
        ctx.housekeeping.create_task({"room_id": r.id, "task_type": "deep_clean"})
    ctx.auth.login("maria", "Password123")
    ctx.housekeeping.start(task.id)
    ctx.housekeeping.complete(task.id)
    with pytest.raises(PermissionDenied):
        ctx.housekeeping.inspect(task.id, True)
    login_as(ctx, "Manager")
    with pytest.raises(ValidationError):
        ctx.housekeeping.inspect(task.id, False, "")
    ctx.housekeeping.inspect(task.id, False, "Bathroom mirror streaky")
    t = ctx.housekeeping.get(task.id)
    assert t.status == TaskStatus.PENDING and t.inspection_notes == "Bathroom mirror streaky"
    assert room(ctx, "101").hk_status == HKStatus.DIRTY
    assert other.user_id != maria.user_id


def test_require_inspection_policy_and_daily_tasks(ctx):
    ctx.settings.update({"policy.require_inspection": True})
    r = room(ctx, "101")
    ctx.housekeeping.set_room_status(r.id, HKStatus.CLEAN)
    assert state(ctx, "101") == RoomState.VACANT_DIRTY  # clean but not inspected
    ctx.housekeeping.set_room_status(r.id, HKStatus.INSPECTED)
    assert state(ctx, "101") == RoomState.AVAILABLE
    res_id = book(ctx, new_guest(ctx), "102", nights=3)
    ctx.clock.set(datetime(2026, 3, 10, 15))
    ctx.reservations.check_in(res_id, allow_dirty=True)
    ctx.clock.set(datetime(2026, 3, 11, 8))
    ctx.housekeeping.set_room_status(room(ctx, "201").id, HKStatus.DIRTY)
    created = ctx.housekeeping.generate_daily_tasks()
    assert created == 1  # stayover for 102; 201 already has a task
    assert ctx.housekeeping.generate_daily_tasks() == 0
    summary = ctx.housekeeping.summary()
    assert summary.pending_tasks == 2 and summary.dirty == 1


def test_dirty_room_with_arrival_is_urgent(ctx):
    book(ctx, new_guest(ctx), "201", nights=1)
    ctx.housekeeping.set_room_status(room(ctx, "201").id, HKStatus.DIRTY)
    task = ctx.housekeeping.tasks(statuses=["pending"], room_id=room(ctx, "201").id)[0]
    assert task.priority == 1 and task.arrival_today
    assert any(a.key == f"hkarrival:{room(ctx, '201').id}" for a in ctx.alerts.current())


def test_housekeeping_counts_match_the_lists(ctx):
    """A brand-new motel has nothing awaiting inspection; a cleaned departure room shows up once."""
    total = len(ctx.rooms.list_rooms())
    summary = ctx.housekeeping.summary()
    assert summary.awaiting_inspection == 0 and summary.ready == total
    res_id = book(ctx, new_guest(ctx), "101", nights=1)
    ctx.clock.set(datetime(2026, 3, 10, 15))
    ctx.reservations.check_in(res_id)
    ctx.clock.set(datetime(2026, 3, 11, 10))
    ctx.reservations.check_out(res_id, payment={"amount": str(ctx.billing.balance(res_id) / 100),
                                                "method_id": ctx.catalog.payment_methods()[0].id})
    assert ctx.housekeeping.summary().ready == total - 1
    task = ctx.housekeeping.tasks(statuses=["pending"], room_id=room(ctx, "101").id)[0]
    ctx.housekeeping.start(task.id)
    ctx.housekeeping.complete(task.id)
    summary = ctx.housekeeping.summary()
    assert summary.awaiting_inspection == len(ctx.housekeeping.awaiting_inspection()) == 1
    assert summary.ready == total  # inspection is optional by default, so a clean room can be sold
    ctx.housekeeping.inspect(task.id, True)
    assert ctx.housekeeping.summary().awaiting_inspection == 0
