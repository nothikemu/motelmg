"""Application shell: sidebar navigation, top bar, alerts and page stack."""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
                               QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from motelmg import APP_DISPLAY_NAME, __version__
from motelmg.ui import theme as theme_mod
from motelmg.ui.actions import Actions
from motelmg.ui.fmt import Formatter
from motelmg.ui.icons import app_icon
from motelmg.ui.widgets import forms
from motelmg.ui.widgets.common import clear_layout, Avatar, Badge, ElidedLabel, button, icon_button, label, set_icon
from motelmg.ui.widgets.dialogs import guarded
from motelmg.ui.widgets.toast import ToastManager

log = logging.getLogger(__name__)

SEVERITY_ICON = {"critical": ("alert-circle", "red"), "warning": ("alert", "amber"), "info": ("info", "blue")}


class ActivityWatcher(QObject):
    """Tracks the last user input for auto-lock."""

    def __init__(self):
        super().__init__()
        self.last = datetime.now()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel):
            self.last = datetime.now()
        return False


class AlertsPopup(QFrame):
    def __init__(self, window: "MainWindow"):
        super().__init__(window, Qt.WindowType.Popup)
        self.w = window
        self.setObjectName("Popup")
        self.setFixedWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 12, 12, 8)
        head.addWidget(label("Alerts", "h3"))
        head.addStretch(1)
        self.restore_btn = button("Show dismissed", variant="link", small=True, on_click=self._restore)
        head.addWidget(self.restore_btn)
        layout.addLayout(head)
        self.list_host = QWidget()
        self.list_host.setObjectName("Transparent")
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(8, 0, 8, 8)
        self.list_layout.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.list_host)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(120)
        scroll.setMaximumHeight(520)
        layout.addWidget(scroll)

    def populate(self, alerts) -> None:
        clear_layout(self.list_layout)
        if not alerts:
            empty = label("You're all caught up. Nothing needs attention right now.", "muted", wrap=True)
            empty.setContentsMargins(10, 18, 10, 18)
            self.list_layout.addWidget(empty)
        for alert in alerts[:40]:
            self.list_layout.addWidget(self._row(alert))
        self.list_layout.addStretch(1)
        self.adjustSize()

    def _row(self, alert) -> QWidget:
        row = QFrame()
        row.setProperty("soft", True)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 8, 6, 8)
        lay.setSpacing(10)
        ic = QLabel()
        name, tone = SEVERITY_ICON.get(alert.severity, SEVERITY_ICON["info"])
        set_icon(ic, name, tone, 17)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(alert.title, "h3"))
        text.addWidget(label(alert.message, "faint", wrap=True))
        lay.addLayout(text, 1)
        open_btn = icon_button("arrow-right", "Open", lambda a=alert: self._open(a), size=15)
        dismiss = icon_button("x", "Dismiss for today", lambda a=alert: self._dismiss(a), size=14)
        lay.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(dismiss, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _open(self, alert) -> None:
        self.hide()
        self.w.actions.open_alert(alert)

    def _dismiss(self, alert) -> None:
        self.w.ctx.alerts.dismiss(alert.key)
        self.populate(self.w.ctx.alerts.current())
        self.w.update_alert_badge()

    def _restore(self) -> None:
        self.w.ctx.alerts.restore_dismissed()
        self.populate(self.w.ctx.alerts.current())
        self.w.update_alert_badge()


class SearchLauncher(QPushButton):
    """The top bar search box. Uses a shorter hint when the window is narrow."""

    LONG = "  Search guests, reservations, rooms…     Ctrl+K"
    SHORT = "  Search…   Ctrl+K"

    def __init__(self):
        super().__init__(self.LONG)

    def _hint_for(self, text: str) -> QSize:
        # Measured on demand so the themed font and padding are taken into account.
        base = super().sizeHint()
        metrics = self.fontMetrics()
        return QSize(base.width() + metrics.horizontalAdvance(text) - metrics.horizontalAdvance(self.text()),
                     base.height())

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._hint_for(self.LONG)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self._hint_for(self.SHORT)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.setText(self.LONG if self.width() >= self._hint_for(self.LONG).width() else self.SHORT)
        super().resizeEvent(event)


class MainWindow(QMainWindow):
    signed_out = Signal()
    restored = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.fmt = Formatter(ctx)
        forms.DATE_DISPLAY = self.fmt.date_format
        self.actions = Actions(self)
        self.setWindowTitle(f"{ctx.settings.property_name} — {APP_DISPLAY_NAME}")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1000, 560)  # the layout itself sets the real floor (fits 1280x720 screens)
        self.pages: dict[str, object] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self._closing_for_signout = False
        self._last_alert_keys: set[str] = set()

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_topbar())
        self.stack = QStackedWidget()
        self.stack.setObjectName("Pages")
        right.addWidget(self.stack, 1)
        root_layout.addLayout(right, 1)
        self.setCentralWidget(root)
        self.toasts = ToastManager(self)
        self.toasts.enabled = ctx.settings.get_bool("notify.toasts")

        self._build_pages()
        self._shortcuts()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(60)
        self._refresh_timer.timeout.connect(self._do_refresh)
        self._dirty_topics: set[str] = set()
        ctx.events.subscribe("*", self._on_data_event)
        self._tick = QTimer(self)
        self._tick.setInterval(60_000)
        self._tick.timeout.connect(self._minute_tick)
        self._tick.start()
        self.activity = ActivityWatcher()
        QApplication.instance().installEventFilter(self.activity)
        theme_mod.theme_manager.changed.connect(self._theme_changed)
        first = next(iter(self.pages))
        self.navigate("dashboard" if "dashboard" in self.pages else first)
        self.update_alert_badge(initial=True)

    # -- layout --------------------------------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(236)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 16, 0, 14)
        layout.setSpacing(0)
        brand = QHBoxLayout()
        brand.setContentsMargins(18, 0, 14, 10)
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(36, 36))
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.brand_name = QLabel(self.ctx.settings.property_name)
        self.brand_name.setObjectName("BrandName")
        self.brand_name.setWordWrap(True)
        sub = QLabel(f"{APP_DISPLAY_NAME} · v{__version__}")
        sub.setObjectName("BrandSub")
        names.addWidget(self.brand_name)
        names.addWidget(sub)
        brand.addLayout(names, 1)
        layout.addLayout(brand)
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(0)
        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        nav_scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget "
                                 "{ background: transparent; }")
        host = QWidget()
        host.setLayout(self.nav_layout)
        nav_scroll.setWidget(host)
        layout.addWidget(nav_scroll, 1)

        chip = QFrame()
        chip.setObjectName("UserChip")
        cl = QHBoxLayout(chip)
        cl.setContentsMargins(10, 8, 6, 8)
        cl.setSpacing(10)
        session = self.ctx.session
        cl.addWidget(Avatar(session.full_name if session else "?", 34))
        who = QVBoxLayout()
        who.setSpacing(0)
        name = QLabel(session.full_name if session else "")
        name.setObjectName("UserName")
        role = QLabel(session.role_name if session else "")
        role.setObjectName("BrandSub")
        who.addWidget(name)
        who.addWidget(role)
        cl.addLayout(who, 1)
        menu_btn = QToolButton()
        menu_btn.setObjectName("UserMenu")
        set_icon(menu_btn, "more", "#a5b4c8", 18)
        menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_btn)
        menu.addAction("Change password…", self._change_password)
        menu.addAction("Lock screen  (Ctrl+L)", self.lock)
        menu.addAction("Keyboard shortcuts  (F1)", self._shortcuts_help)
        menu.addSeparator()
        menu.addAction("Sign out", self.sign_out)
        menu_btn.setMenu(menu)
        cl.addWidget(menu_btn)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(12, 8, 12, 0)
        wrap.addWidget(chip)
        layout.addLayout(wrap)
        return side

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(66)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 8, 18, 8)
        layout.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.page_title = ElidedLabel("")
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = ElidedLabel("")
        self.page_subtitle.setObjectName("PageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        layout.addLayout(titles, 1)
        self.search_btn = SearchLauncher()
        self.search_btn.setObjectName("SearchLauncher")
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_icon(self.search_btn, "search", "text_faint", 15)
        self.search_btn.clicked.connect(lambda: self.actions.search())
        layout.addWidget(self.search_btn)
        layout.addSpacing(6)
        if self.ctx.can("reservations.create") and self.ctx.can("reservations.checkin"):
            layout.addWidget(button("Walk-in", "log-in", None, on_click=lambda: self.actions.walk_in(),
                                    tooltip="Register and check in a guest arriving now (Ctrl+Shift+N)"))
        if self.ctx.can("reservations.create"):
            layout.addWidget(button("New reservation", "plus", "primary",
                                    on_click=lambda: self.actions.new_reservation(),
                                    tooltip="Create a reservation (Ctrl+N)"))
        bell_host = QWidget()
        bell_host.setObjectName("Transparent")
        bell_host.setFixedSize(42, 40)
        self.bell = icon_button("bell", "Alerts", self._show_alerts, size=19)
        self.bell.setParent(bell_host)
        self.bell.move(2, 2)
        self.bell_badge = QLabel("", bell_host)
        self.bell_badge.setObjectName("Badge")
        self.bell_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bell_badge.setMinimumWidth(17)
        self.bell_badge.setFixedHeight(17)
        self.bell_badge.move(22, 1)
        self.bell_badge.hide()
        layout.addWidget(bell_host)
        self.theme_btn = icon_button("moon", "Toggle dark mode", self._toggle_theme, size=18)
        layout.addWidget(self.theme_btn)
        layout.addWidget(icon_button("help", "Keyboard shortcuts (F1)", self._shortcuts_help, size=18))
        self.alerts_popup = AlertsPopup(self)
        self._theme_changed()
        return bar

    def _build_pages(self) -> None:
        from motelmg.ui.pages.audit import AuditPage
        from motelmg.ui.pages.billing import BillingPage
        from motelmg.ui.pages.calendar import CalendarPage
        from motelmg.ui.pages.dashboard import DashboardPage
        from motelmg.ui.pages.guests import GuestsPage
        from motelmg.ui.pages.housekeeping import HousekeepingPage
        from motelmg.ui.pages.maintenance import MaintenancePage
        from motelmg.ui.pages.reports import ReportsPage
        from motelmg.ui.pages.reservations import ReservationsPage
        from motelmg.ui.pages.rooms import RoomsPage
        from motelmg.ui.pages.settings import SettingsPage
        from motelmg.ui.pages.staff import StaffPage

        sections = [
            ("FRONT DESK", [DashboardPage, RoomsPage, CalendarPage, ReservationsPage, GuestsPage]),
            ("OPERATIONS", [HousekeepingPage, MaintenancePage]),
            ("BUSINESS", [BillingPage, ReportsPage]),
            ("ADMINISTRATION", [StaffPage, AuditPage, SettingsPage]),
        ]
        index = 0
        for title, classes in sections:
            allowed = [c for c in classes if c.allowed(self.ctx)]
            if not allowed:
                continue
            section = QLabel(title)
            section.setObjectName("NavSection")
            self.nav_layout.addWidget(section)
            for cls in allowed:
                page = cls(self)
                self.pages[cls.key] = page
                self.stack.addWidget(page)
                btn = QPushButton(f"  {cls.title}")
                btn.setProperty("nav", True)
                btn.setCheckable(True)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                set_icon(btn, cls.icon, "sidebar_text", 18)
                index += 1
                if index <= 9:
                    btn.setToolTip(f"{cls.title} (Ctrl+{index})")
                btn.clicked.connect(lambda _=False, k=cls.key: self.navigate(k))
                self.nav_buttons[cls.key] = btn
                self.nav_layout.addWidget(btn)
        self.nav_layout.addStretch(1)

    def _shortcuts(self) -> None:
        def sc(seq, fn):
            QShortcut(QKeySequence(seq), self, activated=fn)

        sc("Ctrl+K", lambda: self.actions.search())
        sc("Ctrl+F", lambda: self.actions.search())
        sc("Ctrl+N", lambda: self.actions.new_reservation())
        sc("Ctrl+Shift+N", lambda: self.actions.walk_in())
        sc("Ctrl+G", lambda: self.actions.new_guest())
        sc("Ctrl+L", self.lock)
        sc("F5", self.refresh_current)
        sc("F1", self._shortcuts_help)
        for i, key in enumerate(list(self.pages)[:9], start=1):
            sc(f"Ctrl+{i}", lambda k=key: self.navigate(k))

    # -- navigation ------------------------------------------------------------------------------------
    def navigate(self, key: str, **kwargs) -> None:
        page = self.pages.get(key)
        if page is None:
            self.toast("You don't have access to that section.", "warning")
            return
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)
        self.stack.setCurrentWidget(page)
        self.page_title.setText(page.title)
        page.on_show(**kwargs)
        self.page_subtitle.setText(page.subtitle())

    def current_page(self):
        return self.stack.currentWidget()

    def refresh_current(self) -> None:
        page = self.current_page()
        if page:
            page.safe_refresh()
            self.page_subtitle.setText(page.subtitle())
        self.update_alert_badge()

    def refresh_soon(self) -> None:
        self._dirty_topics.add("*")
        self._refresh_timer.start()

    def _on_data_event(self, topic: str) -> None:
        for t in topic.split(","):
            self._dirty_topics.add(t)
        self._refresh_timer.start()

    def _do_refresh(self) -> None:
        topics, self._dirty_topics = self._dirty_topics, set()
        if "settings" in topics or "*" in topics:
            self.brand_name.setText(self.ctx.settings.property_name)
            self.setWindowTitle(f"{self.ctx.settings.property_name} — {APP_DISPLAY_NAME}")
            self.toasts.enabled = self.ctx.settings.get_bool("notify.toasts")
            forms.DATE_DISPLAY = self.fmt.date_format
        for page in self.pages.values():
            if "*" in topics or set(page.topics) & topics or not page.topics:
                page.mark_stale()
        page = self.current_page()
        if page:
            self.page_subtitle.setText(page.subtitle())
        self.update_alert_badge()

    def _minute_tick(self) -> None:
        minutes = self.ctx.settings.get_int("app.auto_lock_minutes")
        if minutes and (datetime.now() - self.activity.last).total_seconds() >= minutes * 60:
            if not QApplication.activeModalWidget():
                self.lock()
                return
        page = self.current_page()
        if page and page.key in ("dashboard", "rooms"):
            page.mark_stale()
        self.update_alert_badge()

    # -- alerts ---------------------------------------------------------------------------------------
    def update_alert_badge(self, initial: bool = False) -> None:
        try:
            alerts = self.ctx.alerts.current()
        except Exception:  # noqa: BLE001
            log.exception("Computing alerts failed")
            return
        important = [a for a in alerts if a.severity in ("critical", "warning")]
        count = len(important)
        self.bell_badge.setText(str(count) if count < 100 else "99+")
        self.bell_badge.adjustSize()
        self.bell_badge.setVisible(count > 0)
        keys = {a.key for a in alerts if a.severity == "critical"}
        new = keys - self._last_alert_keys
        if new and not initial and self.ctx.settings.get_bool("notify.toasts"):
            alert = next(a for a in alerts if a.key in new)
            self.toast(f"{alert.title}: {alert.message}", "warning", 6000)
        self._last_alert_keys = keys

    def _show_alerts(self) -> None:
        self.alerts_popup.populate(self.ctx.alerts.current())
        pos = self.bell.mapToGlobal(QPoint(self.bell.width(), self.bell.height() + 6))
        self.alerts_popup.move(pos.x() - self.alerts_popup.width(), pos.y())
        self.alerts_popup.show()

    # -- misc -------------------------------------------------------------------------------------------
    def toast(self, message: str, tone: str = "success", duration: int = 3800) -> None:
        self.toasts.show(message, tone, duration)

    def _toggle_theme(self) -> None:
        new = "light" if theme_mod.theme().dark else "dark"
        theme_mod.theme_manager.apply(new)
        guarded(self, lambda: self.ctx.settings.update({"app.theme": new}, audit=False, require_permission=False))

    def _theme_changed(self) -> None:
        set_icon(self.theme_btn, "sun" if theme_mod.theme().dark else "moon", "text_muted", 18)
        for page in getattr(self, "pages", {}).values():
            page.update()

    def _shortcuts_help(self) -> None:
        from motelmg.ui.dialogs.misc import ShortcutsDialog
        ShortcutsDialog(self).exec()

    def _change_password(self) -> None:
        from motelmg.ui.dialogs.staff import ChangePasswordDialog
        ChangePasswordDialog(self, self).exec()

    def lock(self) -> None:
        from motelmg.ui.login import LockDialog
        dlg = LockDialog(self, self.ctx)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.sign_out()
            return
        self.activity.last = datetime.now()

    def sign_out(self) -> None:
        guarded(self, self.ctx.auth.logout)
        self._closing_for_signout = True
        self.close()
        self.signed_out.emit()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._tick.stop()
        try:
            QApplication.instance().removeEventFilter(self.activity)
        except RuntimeError:
            pass
        self.ctx.events.unsubscribe("*", self._on_data_event)
        super().closeEvent(event)
        if not self._closing_for_signout:
            QApplication.quit()


__all__ = ["MainWindow", "QAction", "Badge"]
