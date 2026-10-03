"""Application entry point.

Start-up sequence:

1. configure logging and a global crash handler
2. make sure only one instance runs against the same data folder
3. open (and if needed create/migrate) the database
4. first launch -> setup wizard; otherwise -> sign-in screen
5. main window; automatic backups run in the background of the session
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import threading
import traceback

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from motelmg import APP_DISPLAY_NAME, APP_NAME, ORG_NAME, __version__
from motelmg.core import paths
from motelmg.core.errors import MotelError

log = logging.getLogger("motelmg")


def setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(paths.logs_dir() / "motelmg.log", maxBytes=1_000_000,
                                                   backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        root.addHandler(console)
    log.info("Starting %s %s (data dir %s)", APP_NAME, __version__, paths.data_dir())


def install_exception_hook() -> None:
    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.error("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        app = QApplication.instance()
        if app is None:
            return
        try:
            from motelmg.ui.widgets.dialogs import show_error
            show_error(QApplication.activeWindow(), exc)
        except Exception:  # pragma: no cover - last resort
            QMessageBox.critical(None, APP_DISPLAY_NAME, f"Unexpected error: {exc}")

    sys.excepthook = hook
    threading.excepthook = lambda args: hook(args.exc_type, args.exc_value, args.exc_traceback)


class AppController:
    def __init__(self, app: QApplication):
        self.app = app
        self.ctx = None
        self.window = None
        self.login = None

    # -- database ------------------------------------------------------------------------------------------
    def open_database(self) -> bool:
        from motelmg.services.context import AppContext
        db_path = paths.database_path()
        while True:
            try:
                self.ctx = AppContext(db_path)
                return True
            except MotelError as exc:
                log.exception("Database could not be opened")
                message = exc.message
            except Exception as exc:  # noqa: BLE001
                log.exception("Database could not be opened")
                message = str(exc)
            box = QMessageBox(QMessageBox.Icon.Critical, APP_DISPLAY_NAME,
                              f"The database could not be opened:\n\n{message}\n\nDatabase file:\n{db_path}")
            restore = box.addButton("Restore from a backup…", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not restore:
                return False
            file, _ = QFileDialog.getOpenFileName(None, "Choose a backup", str(paths.default_backup_dir()),
                                                  "MotelMG database (*.db);;All files (*)")
            if not file:
                return False
            try:
                from motelmg.data.backup import replace_database_file
                replace_database_file(db_path, file)
            except MotelError as exc:
                QMessageBox.critical(None, APP_DISPLAY_NAME, exc.message)

    # -- flow ------------------------------------------------------------------------------------------------
    def start(self) -> bool:
        if not self.open_database():
            return False
        from motelmg.services.setup import SetupService
        from motelmg.ui.theme import theme_manager
        theme_manager.apply(self.ctx.settings.get_str("app.theme") or "light")
        if SetupService(self.ctx).needed():
            from motelmg.ui.wizard import SetupWizard
            wizard = SetupWizard(self.ctx)
            if wizard.exec() != QDialog.DialogCode.Accepted:
                return False
            theme_manager.apply(self.ctx.settings.get_str("app.theme") or "light")
            self.show_main()
        else:
            self.show_login()
        return True

    def show_login(self) -> None:
        from motelmg.ui.login import LoginWindow
        if self.window is not None:
            self.window.deleteLater()
            self.window = None
        self.login = LoginWindow(self.ctx)
        self.login.logged_in.connect(self._logged_in)
        self.login.show()

    def _logged_in(self) -> None:
        session = self.ctx.session
        if session and session.must_change_password:
            from motelmg.ui.dialogs.staff import ChangePasswordDialog

            class _Shim:  # minimal 'app' for the dialog before the main window exists
                ctx = self.ctx

                @staticmethod
                def toast(*_args, **_kwargs):
                    pass

            dlg = ChangePasswordDialog(self.login, _Shim(), forced=True)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self.ctx.auth.logout()
                if self.login is not None:
                    self.login._success = False
                return
        if self.login is not None:
            self.login.close()
            self.login.deleteLater()
            self.login = None
        self.show_main()

    def show_main(self) -> None:
        from motelmg.ui.main_window import MainWindow
        self.window = MainWindow(self.ctx)
        self.window.signed_out.connect(lambda: QTimer.singleShot(0, self.show_login))
        self.window.restored.connect(self._after_restore)
        self.window.resize(1440, 900)
        self.window.showMaximized() if os.environ.get("MOTELMG_MAXIMIZE", "1") == "1" else self.window.show()
        QTimer.singleShot(2500, self._auto_backup)

    def _after_restore(self) -> None:
        from motelmg.ui.theme import theme_manager
        if self.window is not None:
            self.window._closing_for_signout = True
            self.window.close()
        theme_manager.apply(self.ctx.settings.get_str("app.theme") or "light")
        QTimer.singleShot(0, self.show_login)

    def _auto_backup(self) -> None:
        if self.ctx is None:
            return
        path = self.ctx.backups.auto_backup_if_due()
        if path:
            log.info("Automatic backup created: %s", path)

    def shutdown(self) -> None:
        if self.ctx is None:
            return
        try:
            self.ctx.backups.backup_on_exit()
        finally:
            self.ctx.close()
            log.info("Shut down cleanly")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Motel management system")
    parser.add_argument("--data-dir", help="store the database, logs and backups in this folder")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args, _ = parser.parse_known_args(argv)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.data_dir:
        paths.set_data_dir_override(args.data_dir)
    setup_logging()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)  # windows are swapped on sign-in / sign-out
    from motelmg.ui.icons import app_icon
    from motelmg.ui.theme import load_fonts
    app.setWindowIcon(app_icon())
    load_fonts()
    install_exception_hook()

    lock = QLockFile(str(paths.data_dir() / "motelmg.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QMessageBox.information(None, APP_DISPLAY_NAME, f"{APP_DISPLAY_NAME} is already running.\n\n"
                                "Switch to the open window (check the taskbar).")
        return 0
    controller = AppController(app)
    try:
        if not controller.start():
            controller.shutdown()
            return 0
        app.aboutToQuit.connect(controller.shutdown)
        return app.exec()
    finally:
        lock.unlock()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
