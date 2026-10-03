from datetime import timedelta

import pytest

from motelmg.core.errors import AuthenticationError, ConflictError, PermissionDenied, ValidationError
from tests.conftest import ADMIN, login_as


def role_id(ctx, name):
    return next(r.id for r in ctx.users.list_roles() if r.name == name)


def test_login_logout_and_audit(ctx):
    ctx.auth.logout()
    assert ctx.session is None
    with pytest.raises(AuthenticationError):
        ctx.auth.login("admin", "wrong-password1")
    session = ctx.auth.login("ADMIN", ADMIN["password"])  # usernames are case-insensitive
    assert session.is_admin and session.has("settings.manage")
    actions = [e.action for e in ctx.audit.search()]
    assert "auth.login_failed" in actions and "auth.login" in actions


def test_account_lockout_after_failed_attempts(ctx):
    for _ in range(4):
        with pytest.raises(AuthenticationError, match="Incorrect"):
            ctx.auth.login("admin", "bad")
    with pytest.raises(AuthenticationError, match="locked"):
        ctx.auth.login("admin", "bad")
    with pytest.raises(AuthenticationError, match="locked"):
        ctx.auth.login("admin", ADMIN["password"])
    ctx.clock.advance(minutes=6)
    assert ctx.auth.login("admin", ADMIN["password"])


def test_password_policy_and_change(ctx):
    with pytest.raises(ValidationError):
        ctx.users.create_user({"full_name": "X", "username": "xx1", "role_id": role_id(ctx, "Front Desk")}, "short")
    with pytest.raises(ValidationError):
        ctx.users.create_user({"full_name": "X", "username": "xx1", "role_id": role_id(ctx, "Front Desk")},
                              "lettersonly")
    uid = ctx.users.create_user({"full_name": "Desk Clerk", "username": "clerk", "role_id": role_id(ctx, "Front Desk")},
                                "Temp12345")
    with pytest.raises(ValidationError, match="taken"):
        ctx.users.create_user({"full_name": "Dup", "username": "CLERK", "role_id": role_id(ctx, "Front Desk")},
                              "Temp12345")
    session = ctx.auth.login("clerk", "Temp12345")
    assert session.must_change_password
    with pytest.raises(ValidationError):
        ctx.auth.change_password("wrong", "NewPass123", "NewPass123")
    with pytest.raises(ValidationError):
        ctx.auth.change_password("Temp12345", "NewPass123", "Mismatch123")
    ctx.auth.change_password("Temp12345", "NewPass123", "NewPass123")
    ctx.auth.logout()
    assert not ctx.auth.login("clerk", "NewPass123").must_change_password
    assert uid


def test_role_permissions_are_enforced(ctx):
    login_as(ctx, "Housekeeping")
    with pytest.raises(PermissionDenied):
        ctx.guests.search("")
    with pytest.raises(PermissionDenied):
        ctx.billing.transactions()
    with pytest.raises(PermissionDenied):
        ctx.settings.update({"property.name": "Hacked"})
    assert ctx.housekeeping.tasks() == []
    login_as(ctx, "Front Desk")
    assert ctx.guests.search("") == []
    with pytest.raises(PermissionDenied):
        ctx.users.create_user({"full_name": "Evil", "username": "evil", "role_id": 1}, "Password123")
    with pytest.raises(PermissionDenied):
        ctx.reports.run("daily_revenue", start=ctx.clock.today(), end=ctx.clock.today())
    ctx.reports.run("occupancy", start=ctx.clock.today(), end=ctx.clock.today())


def test_no_privilege_escalation(ctx):
    manager = login_as(ctx, "Manager")
    assert "Administrator" not in [r.name for r in ctx.users.assignable_roles()]
    with pytest.raises(PermissionDenied):
        ctx.users.create_user({"full_name": "Boss", "username": "boss", "role_id": role_id(ctx, "Administrator")},
                              "Password123")
    with pytest.raises(PermissionDenied):
        ctx.users.save_role(None, "Super", "", {"settings.manage"})
    admin_id = ctx.repo_staff.get_user_row("admin")["id"]
    with pytest.raises(PermissionDenied):
        ctx.users.reset_password(admin_id, "Password999")
    ctx.users.create_user({"full_name": "Night Audit", "username": "night", "role_id": role_id(ctx, "Front Desk")},
                          "Password123")
    assert manager.role_name == "Manager"


def test_last_admin_and_self_protection(ctx):
    admin_id = ctx.session.user_id
    with pytest.raises(ConflictError):
        ctx.users.set_active(admin_id, False)
    with pytest.raises(ConflictError):
        ctx.users.update_user(admin_id, {"full_name": "Alex", "role_id": role_id(ctx, "Manager")})
    with pytest.raises(ConflictError):
        ctx.users.save_role(role_id(ctx, "Administrator"), "Administrator", "", {"dashboard.view"})
    with pytest.raises(ConflictError, match="still have this role"):
        login_as(ctx, "Front Desk")
        ctx.auth.login("admin", ADMIN["password"])
        ctx.users.delete_role(role_id(ctx, "Front Desk"))


def test_custom_role_and_deactivation(ctx):
    rid = ctx.users.save_role(None, "Night Auditor", "Overnight desk", {"dashboard.view", "reservations.view",
                                                                       "reports.view"})
    uid = ctx.users.create_user({"full_name": "Nora Night", "username": "nora", "role_id": rid}, "Password123",
                                must_change=False)
    session = ctx.auth.login("nora", "Password123")
    assert session.permissions == {"dashboard.view", "reservations.view", "reports.view"}
    ctx.auth.login("admin", ADMIN["password"])
    ctx.users.set_active(uid, False)
    with pytest.raises(AuthenticationError, match="deactivated"):
        ctx.auth.login("nora", "Password123")
    ctx.users.set_active(uid, True)
    ctx.users.reset_password(uid, "Fresh12345")
    assert ctx.auth.login("nora", "Fresh12345").must_change_password


def test_settings_validation_and_audit(ctx):
    with pytest.raises(ValidationError):
        ctx.settings.update({"property.name": "  "})
    with pytest.raises(ValidationError):
        ctx.settings.update({"policy.check_in_time": "25:99"})
    with pytest.raises(ValidationError):
        ctx.settings.update({"backup.keep": 0})
    ctx.settings.update({"property.name": "Sunset Motel", "policy.check_out_time": "10:30"})
    assert ctx.settings.property_name == "Sunset Motel"
    assert ctx.settings.check_out_time().minute == 30
    assert ctx.audit.search(action_prefix="settings.")[0].summary.startswith("Updated settings")
    assert ctx.clock.today() - timedelta(days=1)
