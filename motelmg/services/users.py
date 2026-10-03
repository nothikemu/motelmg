"""Staff accounts and roles."""

from __future__ import annotations

from typing import Any

from motelmg.core import validation as v
from motelmg.core.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from motelmg.core.permissions import ADMIN_ROLE, PERMISSION_CODES
from motelmg.models import Role, User
from motelmg.services.auth import hash_password, validate_password_strength


class UserService:
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def repo(self):
        return self.ctx.repo_staff

    # -- queries ---------------------------------------------------------------
    def list_users(self, include_inactive: bool = True) -> list[User]:
        return self.repo.list_users(include_inactive)

    def get(self, user_id: int) -> User:
        user = self.repo.get_user(user_id)
        if not user:
            raise NotFoundError("Staff member not found.")
        return user

    def list_roles(self) -> list[Role]:
        return self.repo.list_roles()

    def housekeepers(self) -> list[User]:
        return self.repo.users_with_permission("housekeeping.work")

    def assignable_roles(self) -> list[Role]:
        """Roles the current user may grant (no privilege escalation)."""
        session = self.ctx.session
        roles = self.repo.list_roles()
        if session is None or session.is_admin:
            return roles
        return [r for r in roles if r.name != ADMIN_ROLE and r.permissions <= session.permissions]

    # -- users -----------------------------------------------------------------
    def _validate_user(self, data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        errors: dict[str, str] = {}
        values: dict[str, Any] = {}
        try:
            values["full_name"] = v.required(data.get("full_name"), "Full name", "full_name", max_len=100)
        except ValidationError as exc:
            errors.update(exc.field_errors)
        if creating:
            username = v.clean(data.get("username")).lower()
            if not v.USERNAME_RE.match(username):
                errors["username"] = "Username must be 3-32 characters: letters, numbers, dot, dash or underscore."
            values["username"] = username
        try:
            values["email"] = v.email(data.get("email"))
        except ValidationError as exc:
            errors.update(exc.field_errors)
        try:
            values["phone"] = v.phone(data.get("phone"))
        except ValidationError as exc:
            errors.update(exc.field_errors)
        role_id = data.get("role_id")
        role = self.repo.get_role(int(role_id)) if role_id else None
        if role is None:
            errors["role_id"] = "Select a role."
        values["role_id"] = role.id if role else None
        if errors:
            raise ValidationError(field_errors=errors)
        assert role is not None
        if self.ctx.session is not None and role.id not in {r.id for r in self.assignable_roles()}:
            raise PermissionDenied("You cannot assign a role with more access than your own.")
        return values

    def create_user(self, data: dict[str, Any], password: str, *, must_change: bool = True) -> int:
        bootstrap = not self.ctx.auth.has_users()
        if not bootstrap:
            self.ctx.require("staff.manage")
        values = self._validate_user(data, creating=True)
        validate_password_strength(password, username=values["username"])
        if self.repo.get_user_row(values["username"]):
            raise ValidationError("This username is already taken.", field="username")
        now = self.ctx.now_str()
        values.update({"password_hash": hash_password(password), "must_change_password": int(must_change),
                       "created_at": now, "updated_at": now, "password_changed_at": now})
        with self.ctx.db.transaction():
            user_id = self.repo.insert_user(values)
            self.ctx.audit.log("staff.create", "user", user_id,
                               f"Created staff account '{values['username']}' ({values['full_name']})")
        self.ctx.events.emit("staff")
        return user_id

    def update_user(self, user_id: int, data: dict[str, Any]) -> None:
        self.ctx.require("staff.manage")
        user = self.get(user_id)
        self._guard_admin_target(user)
        values = self._validate_user(data, creating=False)
        admin_role = self.repo.get_role_by_name(ADMIN_ROLE)
        if admin_role and user.role_id == admin_role.id and values["role_id"] != admin_role.id \
                and self.repo.count_active_with_role(admin_role.id, exclude_user=user_id) == 0:
            raise ConflictError("At least one active Administrator account must remain.")
        if self.ctx.session and user_id == self.ctx.session.user_id and values["role_id"] != user.role_id:
            raise ConflictError("You cannot change your own role.")
        values["updated_at"] = self.ctx.now_str()
        with self.ctx.db.transaction():
            self.repo.update_user(user_id, values)
            self.ctx.audit.log("staff.update", "user", user_id, f"Updated staff account '{user.username}'",
                               {k: values[k] for k in ("full_name", "email", "phone", "role_id")})
        if self.ctx.session and user_id == self.ctx.session.user_id:
            self.ctx.auth.refresh_session()
        self.ctx.events.emit("staff")

    def set_active(self, user_id: int, active: bool) -> None:
        self.ctx.require("staff.manage")
        user = self.get(user_id)
        self._guard_admin_target(user)
        if not active:
            if self.ctx.session and user_id == self.ctx.session.user_id:
                raise ConflictError("You cannot deactivate your own account.")
            admin_role = self.repo.get_role_by_name(ADMIN_ROLE)
            if admin_role and user.role_id == admin_role.id and \
                    self.repo.count_active_with_role(admin_role.id, exclude_user=user_id) == 0:
                raise ConflictError("At least one active Administrator account must remain.")
        with self.ctx.db.transaction():
            self.repo.update_user(user_id, {"is_active": int(active), "updated_at": self.ctx.now_str(),
                                            "failed_attempts": 0, "locked_until": None})
            self.ctx.audit.log("staff.activate" if active else "staff.deactivate", "user", user_id,
                               f"{'Activated' if active else 'Deactivated'} staff account '{user.username}'")
        self.ctx.events.emit("staff")

    def reset_password(self, user_id: int, new_password: str) -> None:
        self.ctx.require("staff.manage")
        user = self.get(user_id)
        self._guard_admin_target(user)
        validate_password_strength(new_password, username=user.username)
        with self.ctx.db.transaction():
            self.repo.update_user(user_id, {
                "password_hash": hash_password(new_password), "must_change_password": 1,
                "failed_attempts": 0, "locked_until": None, "updated_at": self.ctx.now_str(),
                "password_changed_at": self.ctx.now_str()})
            self.ctx.audit.log("staff.password_reset", "user", user_id,
                               f"Reset password for '{user.username}'")
        self.ctx.events.emit("staff")

    def unlock(self, user_id: int) -> None:
        self.ctx.require("staff.manage")
        user = self.get(user_id)
        with self.ctx.db.transaction():
            self.repo.update_user(user_id, {"failed_attempts": 0, "locked_until": None})
            self.ctx.audit.log("staff.unlock", "user", user_id, f"Unlocked account '{user.username}'")
        self.ctx.events.emit("staff")

    def _guard_admin_target(self, user: User) -> None:
        session = self.ctx.session
        if session and not session.is_admin and user.role_name == ADMIN_ROLE:
            raise PermissionDenied("Only an Administrator can modify Administrator accounts.")

    # -- roles -------------------------------------------------------------------
    def save_role(self, role_id: int | None, name: str, description: str, permissions: set[str]) -> int:
        self.ctx.require("staff.manage")
        name = v.required(name, "Role name", "name", max_len=50)
        description = v.optional(description, "Description", "description", max_len=300)
        unknown = set(permissions) - PERMISSION_CODES
        if unknown:
            raise ValidationError(f"Unknown permission: {sorted(unknown)[0]}")
        if not permissions:
            raise ValidationError("Select at least one permission for this role.")
        session = self.ctx.session
        if session and not session.is_admin and not set(permissions) <= session.permissions:
            raise PermissionDenied("You cannot grant permissions that you do not have yourself.")
        with self.ctx.db.transaction():
            if role_id:
                role = self.repo.get_role(role_id)
                if not role:
                    raise NotFoundError("Role not found.")
                if role.is_system:
                    raise ConflictError("The Administrator role always has full access and cannot be edited.")
                self.repo.update_role(role_id, name, description)
                action, summary = "staff.role_update", f"Updated role '{name}'"
            else:
                role_id = self.repo.insert_role(name, description, self.ctx.now_str())
                action, summary = "staff.role_create", f"Created role '{name}'"
            self.repo.set_permissions(role_id, set(permissions))
            self.ctx.audit.log(action, "role", role_id, summary, {"permissions": sorted(permissions)})
        self.ctx.auth.refresh_session()
        self.ctx.events.emit("staff")
        return role_id

    def delete_role(self, role_id: int) -> None:
        self.ctx.require("staff.manage")
        role = self.repo.get_role(role_id)
        if not role:
            raise NotFoundError("Role not found.")
        if role.is_system:
            raise ConflictError("The Administrator role cannot be deleted.")
        if role.user_count:
            raise ConflictError(f"{role.user_count} staff member(s) still have this role. "
                                "Assign them a different role first.")
        with self.ctx.db.transaction():
            self.repo.delete_role(role_id)
            self.ctx.audit.log("staff.role_delete", "role", role_id, f"Deleted role '{role.name}'")
        self.ctx.events.emit("staff")
