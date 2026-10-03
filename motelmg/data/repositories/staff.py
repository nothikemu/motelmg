from __future__ import annotations

from typing import Any

from motelmg.data.repositories.base import Repository
from motelmg.models import Role, User, from_row

USER_SELECT = "SELECT u.*, r.name AS role_name FROM users u JOIN roles r ON r.id = u.role_id"


class StaffRepository(Repository):
    # -- users ----------------------------------------------------------------
    def get_user(self, user_id: int) -> User | None:
        row = self.db.one(f"{USER_SELECT} WHERE u.id = ?", (user_id,))
        return from_row(User, row) if row else None

    def get_user_row(self, username: str):
        return self.db.one(f"{USER_SELECT} WHERE u.username = ? COLLATE NOCASE", (username,))

    def password_hash(self, user_id: int) -> str:
        return self.db.scalar("SELECT password_hash FROM users WHERE id = ?", (user_id,), "")

    def list_users(self, include_inactive: bool = True) -> list[User]:
        where = "" if include_inactive else "WHERE u.is_active = 1"
        rows = self.db.query(f"{USER_SELECT} {where} ORDER BY u.is_active DESC, u.full_name COLLATE NOCASE")
        return [from_row(User, r) for r in rows]

    def users_with_permission(self, permission: str) -> list[User]:
        rows = self.db.query(
            f"{USER_SELECT} WHERE u.is_active = 1 AND EXISTS (SELECT 1 FROM role_permissions rp "
            f"WHERE rp.role_id = u.role_id AND rp.permission = ?) ORDER BY u.full_name COLLATE NOCASE",
            (permission,))
        return [from_row(User, r) for r in rows]

    def insert_user(self, values: dict[str, Any]) -> int:
        return self.db.insert("users", values)

    def update_user(self, user_id: int, values: dict[str, Any]) -> None:
        self.db.update("users", user_id, values)

    def count_active_with_role(self, role_id: int, exclude_user: int | None = None) -> int:
        return int(self.db.scalar(
            "SELECT COUNT(*) FROM users WHERE role_id = ? AND is_active = 1 AND id <> ?",
            (role_id, exclude_user or -1), 0))

    def user_count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM users", default=0))

    # -- roles ----------------------------------------------------------------
    def list_roles(self) -> list[Role]:
        rows = self.db.query(
            "SELECT r.*, (SELECT COUNT(*) FROM users u WHERE u.role_id = r.id) AS user_count "
            "FROM roles r ORDER BY r.is_system DESC, r.name COLLATE NOCASE")
        roles = []
        for row in rows:
            role = from_row(Role, row)
            role.permissions = self.permissions(role.id)
            roles.append(role)
        return roles

    def get_role(self, role_id: int) -> Role | None:
        row = self.db.one("SELECT r.*, (SELECT COUNT(*) FROM users u WHERE u.role_id = r.id) AS user_count "
                          "FROM roles r WHERE r.id = ?", (role_id,))
        if not row:
            return None
        role = from_row(Role, row)
        role.permissions = self.permissions(role.id)
        return role

    def get_role_by_name(self, name: str) -> Role | None:
        row = self.db.one("SELECT id FROM roles WHERE name = ? COLLATE NOCASE", (name,))
        return self.get_role(row["id"]) if row else None

    def permissions(self, role_id: int) -> frozenset[str]:
        return frozenset(r[0] for r in self.db.query(
            "SELECT permission FROM role_permissions WHERE role_id = ?", (role_id,)))

    def insert_role(self, name: str, description: str, ts: str) -> int:
        return self.db.insert("roles", {"name": name, "description": description, "created_at": ts})

    def update_role(self, role_id: int, name: str, description: str) -> None:
        self.db.update("roles", role_id, {"name": name, "description": description})

    def set_permissions(self, role_id: int, permissions: set[str]) -> None:
        self.db.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
        self.db.executemany("INSERT INTO role_permissions(role_id, permission) VALUES (?, ?)",
                            [(role_id, p) for p in sorted(permissions)])

    def delete_role(self, role_id: int) -> None:
        self.db.execute("DELETE FROM roles WHERE id = ?", (role_id,))
