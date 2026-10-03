from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from motelmg.core.permissions import ADMIN_ROLE
from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.common import SearchField, button, label
from motelmg.ui.widgets.dialogs import confirm, guarded
from motelmg.ui.widgets.table import Column, DataTable


class StaffPage(Page):
    key = "staff"
    title = "Staff"
    icon = "users"
    permission = "staff.manage"
    topics = ("staff",)

    def __init__(self, app):
        super().__init__(app)
        L = self.layout_
        self.tabs = QTabWidget()
        L.addWidget(self.tabs, 1)
        users = QWidget()
        ul = QVBoxLayout(users)
        ul.setContentsMargins(0, 14, 0, 0)
        ul.setSpacing(12)
        bar = QHBoxLayout()
        self.search = SearchField("Search staff…")
        self.search.textChanged.connect(lambda t: self.users.set_filter_text(t))
        bar.addWidget(self.search)
        bar.addStretch(1)
        bar.addWidget(button("Add staff member", "user-plus", "primary", on_click=self._new_user))
        ul.addLayout(bar)
        self.users = DataTable([
            Column("full_name", "Name", stretch=True, bold=True),
            Column("username", "Username", width=130),
            Column("role_name", "Role", "badge", width=130, tone=lambda r: "indigo" if r["role_name"] == ADMIN_ROLE
                   else "blue"),
            Column("status", "Status", "badge", width=120, fmt=lambda r: r["status_label"], tone=lambda r: r["tone"]),
            Column("email", "Email", width=200),
            Column("last_login_at", "Last sign-in", "datetime", width=170),
        ], self.fmt, empty_icon="users", empty_title="No staff accounts")
        self.users.activated.connect(lambda r: self._edit_user(r["id"]))
        self.users.set_menu_builder(self._user_menu)
        ul.addWidget(self.users, 1)
        ul.addWidget(label("Right-click a staff member to reset their password, unlock or deactivate the account. "
                           "Deactivated staff keep their history in the audit log.", "faint", wrap=True))
        self.tabs.addTab(users, "Staff accounts")

        roles = QWidget()
        rl = QVBoxLayout(roles)
        rl.setContentsMargins(0, 14, 0, 0)
        rl.setSpacing(12)
        rbar = QHBoxLayout()
        rbar.addWidget(label("Roles decide what each staff member can see and do.", "muted"))
        rbar.addStretch(1)
        rbar.addWidget(button("New role", "plus", "primary", on_click=lambda: self._edit_role(None)))
        rl.addLayout(rbar)
        self.roles = DataTable([
            Column("name", "Role", width=180, bold=True),
            Column("description", "Description", stretch=True),
            Column("permissions", "Permissions", "int", width=110),
            Column("user_count", "Staff", "int", width=80),
        ], self.fmt, empty_icon="shield", empty_title="No roles")
        self.roles.activated.connect(lambda r: self._edit_role(r["id"]))
        self.roles.set_menu_builder(lambda r: [("Edit permissions…", lambda: self._edit_role(r["id"])),
                                               ("Delete role…", lambda: self._delete_role(r),
                                                not r["is_system"])])
        rl.addWidget(self.roles, 1)
        self.tabs.addTab(roles, "Roles & permissions")

    def subtitle(self) -> str:
        return "Accounts, roles and permissions"

    def refresh(self) -> None:
        now = self.ctx.clock.now()
        rows = []
        for u in self.ctx.users.list_users():
            locked = bool(u.locked_until and u.locked_until > now)
            label_, tone = ("Locked", "red") if locked else ("Active", "green") if u.is_active else ("Inactive", "gray")
            if u.is_active and u.must_change_password and not locked:
                label_, tone = "Password reset", "amber"
            rows.append({"id": u.id, "full_name": u.full_name, "username": u.username, "role_name": u.role_name,
                         "status_label": label_, "tone": tone, "email": u.email, "last_login_at": u.last_login_at,
                         "is_active": u.is_active, "locked": locked})
        self.users.set_rows(rows)
        self.roles.set_rows([{"id": r.id, "name": r.name, "description": r.description,
                              "permissions": len(r.permissions), "user_count": r.user_count, "is_system": r.is_system}
                             for r in self.ctx.users.list_roles()])

    def _new_user(self) -> None:
        from motelmg.ui.dialogs.staff import UserDialog
        UserDialog(self, self.app).exec()

    def _edit_user(self, user_id: int) -> None:
        from motelmg.ui.dialogs.staff import UserDialog
        UserDialog(self, self.app, user_id).exec()

    def _user_menu(self, row) -> list:
        from motelmg.ui.dialogs.staff import ResetPasswordDialog
        me = self.ctx.session and row["id"] == self.ctx.session.user_id
        return [
            ("Edit…", lambda: self._edit_user(row["id"])),
            ("Reset password…", lambda: ResetPasswordDialog(self, self.app, row["id"]).exec()),
            ("Unlock account", lambda: guarded(self, lambda: self.ctx.users.unlock(row["id"]), "Account unlocked",
                                               self.app.toast), row["locked"]),
            None,
            ("Deactivate…" if row["is_active"] else "Reactivate", lambda: self._toggle_active(row), not me),
        ]

    def _toggle_active(self, row) -> None:
        if row["is_active"] and not confirm(self, "Deactivate account", f"{row['full_name']} will no longer be able "
                                            "to sign in. Their history is kept.", "Deactivate", danger=True):
            return
        guarded(self, lambda: self.ctx.users.set_active(row["id"], not row["is_active"]),
                "Account updated", self.app.toast)

    def _edit_role(self, role_id) -> None:
        from motelmg.ui.dialogs.staff import RoleDialog
        RoleDialog(self, self.app, role_id).exec()

    def _delete_role(self, row) -> None:
        if confirm(self, "Delete role", f"Delete the role '{row['name']}'?", "Delete", danger=True):
            guarded(self, lambda: self.ctx.users.delete_role(row["id"]), "Role deleted", self.app.toast)
