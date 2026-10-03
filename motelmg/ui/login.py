"""Sign-in window and lock screen."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from motelmg import APP_DISPLAY_NAME, __version__
from motelmg.core.errors import MotelError
from motelmg.ui.icons import app_icon
from motelmg.ui.widgets.common import Banner, button, label


def _password() -> QLineEdit:
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setPlaceholderText("Password")
    edit.setMaxLength(128)
    return edit


class LoginWindow(QWidget):
    """Split-screen sign-in: brand panel on the left, form on the right."""

    logged_in = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"Sign in — {APP_DISPLAY_NAME}")
        self.setWindowIcon(app_icon())
        self.resize(980, 620)
        self.setMinimumSize(820, 540)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        brand = QFrame()
        brand.setObjectName("LoginBrand")
        bl = QVBoxLayout(brand)
        bl.setContentsMargins(48, 48, 48, 40)
        bl.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(64, 64))
        bl.addWidget(logo)
        bl.addSpacing(16)
        name = QLabel(ctx.settings.property_name)
        name.setStyleSheet("font-size: 30px; font-weight: 800;")
        name.setWordWrap(True)
        bl.addWidget(name)
        tagline = QLabel("Front desk, housekeeping, billing and reports — all in one place.")
        tagline.setStyleSheet("font-size: 15px; color: rgba(255,255,255,0.85);")
        tagline.setWordWrap(True)
        bl.addWidget(tagline)
        bl.addStretch(1)
        for text in ("Live room board and availability calendar", "Check-in, check-out and folios in seconds",
                     "Housekeeping and maintenance in sync", "Daily revenue and occupancy reports"):
            item = QLabel(f"✓  {text}")
            item.setStyleSheet("font-size: 13.5px; color: rgba(255,255,255,0.92);")
            bl.addWidget(item)
        bl.addSpacing(18)
        foot = QLabel(f"{APP_DISPLAY_NAME} {__version__}")
        foot.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 11px;")
        bl.addWidget(foot)
        root.addWidget(brand, 5)

        right = QWidget()
        right.setObjectName("Page")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(64, 40, 64, 40)
        rl.addStretch(1)
        card = QFrame()
        card.setProperty("card", True)
        card.setMaximumWidth(400)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 32, 32, 30)
        cl.setSpacing(12)
        cl.addWidget(label("Welcome back", "h1"))
        cl.addWidget(label("Sign in with your staff account to continue.", "muted"))
        cl.addSpacing(6)
        self.banner = Banner("", "error")
        cl.addWidget(self.banner)
        cl.addWidget(label("Username", "label"))
        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")
        self.username.setMaxLength(32)
        cl.addWidget(self.username)
        cl.addWidget(label("Password", "label"))
        self.password = _password()
        cl.addWidget(self.password)
        self.caps = label("", "faint")
        cl.addWidget(self.caps)
        cl.addSpacing(4)
        self.submit = button("Sign in", "log-in", "primary", on_click=self._login)
        self.submit.setMinimumHeight(40)
        self.submit.setDefault(True)
        cl.addWidget(self.submit)
        cl.addWidget(label("Forgot your password? Ask a manager or administrator to reset it from the Staff screen.",
                           "faint", wrap=True))
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(card, 10)
        holder.addStretch(1)
        rl.addLayout(holder)
        rl.addStretch(1)
        root.addWidget(right, 6)
        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._login)
        self.username.setFocus()

    def _login(self) -> None:
        self.banner.hide()
        try:
            self.ctx.auth.login(self.username.text(), self.password.text())
        except MotelError as exc:
            self.banner.set(exc.message, "error")
            self.password.clear()
            self.password.setFocus()
            return
        self.password.clear()
        self._success = True
        self.logged_in.emit()

    def closeEvent(self, event) -> None:  # noqa: N802
        super().closeEvent(event)
        if not getattr(self, "_success", False):
            from PySide6.QtWidgets import QApplication
            QApplication.quit()


class LockDialog(QDialog):
    """Screen lock: the signed-in user re-enters their password, or signs out."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Locked")
        self.setModal(True)
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(12)
        layout.addWidget(label("Screen locked", "h2"))
        name = ctx.session.full_name if ctx.session else ""
        layout.addWidget(label(f"Signed in as {name}. Enter your password to continue.", "muted", wrap=True))
        self.banner = Banner("", "error")
        layout.addWidget(self.banner)
        self.password = _password()
        layout.addWidget(self.password)
        row = QHBoxLayout()
        row.addWidget(button("Sign out", "log-out", "ghost", on_click=self.reject))
        row.addStretch(1)
        unlock = button("Unlock", "lock", "primary", on_click=self._unlock)
        unlock.setDefault(True)
        row.addWidget(unlock)
        layout.addLayout(row)
        self.password.returnPressed.connect(self._unlock)
        self.password.setFocus()

    def _unlock(self) -> None:
        if self.ctx.auth.verify_current_user(self.password.text()):
            self.accept()
        else:
            self.banner.set("Incorrect password.", "error")
            self.password.clear()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            return  # cannot dismiss the lock screen with Esc
        super().keyPressEvent(event)


__all__ = ["LoginWindow", "LockDialog", "QPushButton"]
