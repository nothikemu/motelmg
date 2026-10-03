"""Staff accounts, roles/permissions and password dialogs."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from motelmg.core.permissions import ALL_PERMISSIONS
from motelmg.services.auth import MIN_PASSWORD_LENGTH
from motelmg.ui.widgets.common import Banner, label
from motelmg.ui.widgets.dialogs import BaseDialog
from motelmg.ui.widgets.forms import FormGrid, combo, line


def password_field(placeholder: str = "") -> QLineEdit:
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setPlaceholderText(placeholder)
    edit.setMaxLength(128)
    return edit


class UserDialog(BaseDialog):
    def __init__(self, parent, app, user_id: int | None = None):
        self.app, self.ctx, self.user_id = app, app.ctx, user_id
        user = self.ctx.users.get(user_id) if user_id else None
        super().__init__(parent, f"Edit {user.full_name}" if user else "Add staff member",
                         f"@{user.username}" if user else "Create a login for a team member.",
                         icon_name="user-plus", width=560)
        roles = self.ctx.users.assignable_roles()
        self.form = self.register_form(FormGrid(2))
        self.form.add("full_name", "Full name", line(user.full_name if user else "", max_len=100), required=True)
        username = line(user.username if user else "", "e.g. jsmith", 32)
        username.setEnabled(user is None)
        self.form.add("username", "Username", username, required=True)
        self.form.add("email", "Email", line(user.email if user else "", max_len=254))
        self.form.add("phone", "Phone", line(user.phone if user else "", max_len=30))
        role_items = [(r.name, r.id) for r in roles]
        if user and user.role_id not in {r.id for r in roles}:
            role_items.insert(0, (user.role_name, user.role_id))
        self.form.add("role_id", "Role", combo(role_items, user.role_id if user else None), required=True, span=2)
        self.role_desc = label("", "faint", wrap=True)
        self.body.addWidget(self.form)
        self.body.addWidget(self.role_desc)
        self._roles = {r.id: r for r in self.ctx.users.list_roles()}
        self.form.fields["role_id"].currentIndexChanged.connect(self._role_changed)
        self._role_changed()
        if not user:
            self.pw_form = self.register_form(FormGrid(2))
            self.pw = password_field(f"At least {MIN_PASSWORD_LENGTH} characters, letters and numbers")
            self.pw2 = password_field()
            self.pw_form.add("password", "Temporary password", self.pw, required=True)
            self.pw_form.add("confirm", "Confirm password", self.pw2, required=True)
            self.body.addWidget(self.pw_form)
            self.body.addWidget(label("The staff member will be asked to choose their own password at first sign-in.",
                                      "faint", wrap=True))
        self.add_cancel()
        self.add_footer_button("Save" if user else "Create account", self._save, "primary", default=True)

    def _role_changed(self) -> None:
        role = self._roles.get(self.form.fields["role_id"].currentData())
        self.role_desc.setText(f"{role.description} ({len(role.permissions)} permissions)" if role else "")

    def _save(self) -> None:
        values = self.form.values()
        if self.user_id:
            if self.attempt(lambda: self.ctx.users.update_user(self.user_id, values)):
                self.app.toast("Staff member updated")
            return
        if self.pw.text() != self.pw2.text():
            self.pw_form.set_errors({"confirm": "Passwords do not match."})
            return
        if self.attempt(lambda: self.ctx.users.create_user(values, self.pw.text(), must_change=True)):
            self.app.toast(f"Account '{values['username']}' created")


class RoleDialog(BaseDialog):
    def __init__(self, parent, app, role_id: int | None = None):
        self.app, self.ctx, self.role_id = app, app.ctx, role_id
        role = next((r for r in self.ctx.users.list_roles() if r.id == role_id), None)
        super().__init__(parent, f"Role: {role.name}" if role else "New role",
                         "Choose exactly what people with this role may do.", icon_name="shield", width=720)
        self.resize(760, 760)
        self.form = self.register_form(FormGrid(2))
        self.form.add("name", "Role name", line(role.name if role else "", max_len=50), required=True)
        self.form.add("description", "Description", line(role.description if role else "", max_len=300))
        self.body.addWidget(self.form)
        readonly = bool(role and role.is_system)
        if readonly:
            self.body.addWidget(Banner("The Administrator role always has every permission.", "info"))
            self.form.setEnabled(False)
        session = self.ctx.session
        grouped = defaultdict(list)
        for perm in ALL_PERMISSIONS:
            grouped[perm.group].append(perm)
        host = QWidget()
        host.setObjectName("Transparent")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(24)
        self.checks: dict[str, QCheckBox] = {}
        row = 0
        for group, perms in grouped.items():
            grid.addWidget(label(group.upper(), "overline"), row, 0, 1, 2)
            row += 1
            for i, perm in enumerate(perms):
                box = QCheckBox(perm.label)
                box.setToolTip(perm.description or perm.code)
                box.setChecked(bool(role and perm.code in role.permissions))
                box.setEnabled(not readonly and bool(session and (session.is_admin or session.has(perm.code))))
                self.checks[perm.code] = box
                grid.addWidget(box, row + i // 2, i % 2)
            row += (len(perms) + 1) // 2
            grid.setRowMinimumHeight(row, 10)
            row += 1
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(host)
        area.setMinimumHeight(420)
        self.body.addWidget(area, 1)
        self.add_cancel("Close" if readonly else "Cancel")
        if not readonly:
            self.add_footer_button("Save role", self._save, "primary", default=True)

    def _save(self) -> None:
        values = self.form.values()
        perms = {code for code, box in self.checks.items() if box.isChecked()}
        if self.attempt(lambda: self.ctx.users.save_role(self.role_id, values["name"], values["description"], perms)):
            self.app.toast("Role saved")


class ResetPasswordDialog(BaseDialog):
    def __init__(self, parent, app, user_id: int):
        self.app, self.ctx, self.user_id = app, app.ctx, user_id
        user = self.ctx.users.get(user_id)
        super().__init__(parent, f"Reset password for {user.full_name}", "They will have to choose a new password "
                         "the next time they sign in.", icon_name="key", width=460)
        self.form = self.register_form(FormGrid(1))
        self.pw = password_field(f"At least {MIN_PASSWORD_LENGTH} characters, letters and numbers")
        self.pw2 = password_field()
        self.form.add("password", "Temporary password", self.pw, required=True)
        self.form.add("confirm", "Confirm password", self.pw2, required=True)
        self.body.addWidget(self.form)
        self.add_cancel()
        self.add_footer_button("Reset password", self._save, "primary", default=True)

    def _save(self) -> None:
        if self.pw.text() != self.pw2.text():
            self.form.set_errors({"confirm": "Passwords do not match."})
            return
        if self.attempt(lambda: self.ctx.users.reset_password(self.user_id, self.pw.text())):
            self.app.toast("Password reset")


class ChangePasswordDialog(BaseDialog):
    def __init__(self, parent, app, *, forced: bool = False):
        self.app, self.ctx = app, app.ctx
        super().__init__(parent, "Choose a new password" if forced else "Change password",
                         "Your password was set by an administrator. Please choose your own to continue." if forced
                         else "Use at least 8 characters with letters and numbers.", icon_name="lock", width=460)
        self.form = self.register_form(FormGrid(1))
        self.current = password_field()
        self.new = password_field()
        self.confirm = password_field()
        self.form.add("current", "Current password", self.current, required=True)
        self.form.add("new", "New password", self.new, required=True)
        self.form.add("confirm", "Confirm new password", self.confirm, required=True)
        self.body.addWidget(self.form)
        if forced:
            self.add_footer_button("Sign out", self.reject)
        else:
            self.add_cancel()
        self.add_footer_button("Change password", self._save, "primary", default=True)
        self.current.setFocus()

    def _save(self) -> None:
        if self.attempt(lambda: self.ctx.auth.change_password(self.current.text(), self.new.text(),
                                                              self.confirm.text())):
            self.app.toast("Password changed")


__all__ = ["UserDialog", "RoleDialog", "ResetPasswordDialog", "ChangePasswordDialog", "Qt", "QVBoxLayout"]
